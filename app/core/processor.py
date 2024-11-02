from pathlib import Path
import tempfile
import subprocess
import os
import signal
import logging
import json
from typing import List, Dict, Optional, Union
from celery import Task, shared_task

# Import celery app instance from the app package
from app import celery
from app.utils.redis_utils import RedisManager

logger = logging.getLogger(__name__)
class FFmpegProcessor:
    def __init__(self):
        self.temp_dir = Path(tempfile.gettempdir()) / "ffmpeg_api"
        self.keep_files = os.getenv('KEEP_FILES', 'false').lower() == 'true'
        self.ffmpeg_threads = os.getenv('FFMPEG_THREADS', 'auto')
        self.cleanup_interval = int(os.getenv('CLEANUP_INTERVAL', '3600'))
        self.retention_period = int(os.getenv('FILE_RETENTION_PERIOD', '86400'))
        # If FFMPEG_TIMEOUT=0 or not set, it means no timeout (None)
        ffmpeg_timeout = int(os.getenv('FFMPEG_TIMEOUT', '0'))
        self.ffmpeg_timeout = None if ffmpeg_timeout == 0 else ffmpeg_timeout

    def _run_ffmpeg_process(self, command: List[str]) -> subprocess.CompletedProcess:
        """Run FFmpeg process with proper timeout handling and cleanup"""
        process = None
        try:
            logger.info(f"Starting FFmpeg process with timeout: {self.ffmpeg_timeout or 'infinite'}")
            
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=os.setsid
            )
            
            # Pass None for no timeout, or the timeout value if set
            stdout, stderr = process.communicate(timeout=self.ffmpeg_timeout)
            
            if process.returncode != 0:
                raise subprocess.CalledProcessError(
                    process.returncode, 
                    command, 
                    output=stdout, 
                    stderr=stderr
                )
                
            return subprocess.CompletedProcess(
                command, 
                process.returncode, 
                stdout=stdout, 
                stderr=stderr
            )
            
        except subprocess.TimeoutExpired:
            if process:
                logger.warning(f"FFmpeg process timed out after {self.ffmpeg_timeout}s, terminating...")
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        logger.warning("Process didn't terminate gracefully, force killing...")
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                
            raise RuntimeError(f"FFmpeg process timed out after {self.ffmpeg_timeout} seconds")
            
        except Exception as e:
            if process:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            raise

    def _get_ffmpeg_command(self, task_type: str, input_files: List[str], 
                           output_file: str, custom_params: Optional[str] = None) -> List[str]:
        """Build FFmpeg command based on task type"""
        threads = '-threads:v' if task_type != 'normalize' else '-threads'
        thread_count = 'auto' if self.ffmpeg_threads == 'auto' else self.ffmpeg_threads

        base_command = ['ffmpeg']
        
        if thread_count != 'auto':
            base_command.extend([threads, thread_count])

        for input_file in input_files:
            base_command.extend(['-i', input_file])

        if custom_params:
            base_command.extend(custom_params.split())
        else:
            if task_type == 'normalize':
                base_command.extend([
                    '-filter:a', 'loudnorm',
                    '-c:v', 'copy'
                ])
            elif task_type == 'captionize':
                base_command.extend([
                    '-vf', f'subtitles={input_files[1]}',
                    '-c:a', 'copy'
                ])

        base_command.append(output_file)
        return base_command

class FFmpegTask(Task):
    """Base class for FFmpeg Celery tasks"""
    abstract = True

    def on_success(self, retval, task_id, args, kwargs):
        """Handle successful task completion"""
        RedisManager().update_task_status(task_id, 'completed', result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure"""
        RedisManager().update_task_status(task_id, 'failed', error=str(exc))

@celery.task(base=FFmpegTask, bind=True, name='app.core.processor.process_ffmpeg')
def process_ffmpeg(self, task_type: str, input_files: List[str], 
                  output_file: str, custom_params: Optional[str] = None):
    """Process FFmpeg task"""
    processor = FFmpegProcessor()
    RedisManager().update_task_status(self.request.id, 'processing')
    
    try:
        command = processor._get_ffmpeg_command(task_type, input_files, output_file, custom_params)
        logger.info(f"Executing FFmpeg command: {' '.join(command)}")
        
        result = processor._run_ffmpeg_process(command)
        return output_file
        
    except Exception as e:
        logger.exception("FFmpeg processing failed")
        raise