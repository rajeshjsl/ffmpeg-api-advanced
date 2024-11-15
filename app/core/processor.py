from pathlib import Path
import tempfile
import subprocess
import os
import signal
import logging
import json
import mimetypes
import requests
from typing import List, Dict, Optional, Union, Any
from celery import Task, shared_task
import shlex

# Import celery app instance and FileManager
from app import celery
from app.utils.redis_utils import RedisManager
from app.utils.file_manager import FileManager

logger = logging.getLogger(__name__)

class FFmpegProcessor:
    def __init__(self):
        self.temp_dir = Path(tempfile.gettempdir()) / "ffmpeg_api"
        self.ffmpeg_threads = os.getenv('FFMPEG_THREADS', 'auto')
        # If FFMPEG_TIMEOUT=0 or not set, it means no timeout (None)
        ffmpeg_timeout = int(os.getenv('FFMPEG_TIMEOUT', '0'))
        self.ffmpeg_timeout = None if ffmpeg_timeout == 0 else ffmpeg_timeout
        self.file_manager = FileManager()

    def _run_ffmpeg_process(self, command: List[str]) -> subprocess.CompletedProcess:
        """Run FFmpeg process with proper timeout handling"""
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
            
            stdout, stderr = process.communicate(timeout=self.ffmpeg_timeout)
            
            if process.returncode != 0:
                logger.error(f"FFmpeg error output:\n{stderr}")
                logger.error(f"FFmpeg stdout output:\n{stdout}")
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
        base_command = ['ffmpeg']
        
        if self.ffmpeg_threads != 'auto':
            base_command.extend(['-threads', self.ffmpeg_threads])

        if custom_params:
            if task_type == 'normalize':
                custom_params = custom_params.replace('{input}', input_files[0])
            elif task_type == 'captionize':
                custom_params = custom_params.replace('{video}', input_files[0])
                custom_params = custom_params.replace('{subtitle}', input_files[1])
            
            base_command.extend(shlex.split(custom_params))
        else:
            if task_type == 'normalize':
                base_command.extend([
                    '-i', input_files[0],
                    '-filter:a', 'loudnorm',
                    '-c:v', 'copy'
                ])
            elif task_type == 'captionize':
                base_command.extend([
                    '-i', input_files[0],
                    '-vf', f'subtitles={input_files[1]}',
                    '-c:a', 'copy'
                ])

        base_command.append(output_file)
        return base_command

class FFmpegTask(Task):
    """Base class for FFmpeg Celery tasks"""
    abstract = True

    def _send_callback(self, task_id: str, result_path: str, callback_url: str, error: Optional[str] = None):
        """Send callback with result file or error"""
        logger.info(f"Starting callback for task {task_id} to {callback_url}")
        file_manager = FileManager()  # Create FileManager instance
        
        try:
            if error:
                payload = {
                    'task_id': task_id,
                    'status': 'failed',
                    'error': error
                }
                logger.info(f"Sending error callback for task {task_id}: {payload}")
                response = requests.post(callback_url, json=payload)
            else:
                # Determine mime type
                mime_type, _ = mimetypes.guess_type(result_path)
                if not mime_type:
                    mime_type = 'video/mp4'

                logger.info(f"Sending success callback for task {task_id} with file {result_path} (type: {mime_type})")
                
                # Send file in callback
                with open(result_path, 'rb') as f:
                    files = {'file': (os.path.basename(result_path), f, mime_type)}
                    data = {
                        'task_id': task_id,
                        'status': 'completed'
                    }
                    response = requests.post(callback_url, files=files, data=data)
            
            logger.info(f"Callback response for task {task_id}: status={response.status_code}, content={response.text[:200]}")
            
            if not response.ok:
                logger.error(f"Callback failed for task {task_id}: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"Error sending callback for task {task_id} to {callback_url}: {str(e)}", exc_info=True)
        finally:
            # Always attempt to clean up after callback, based on KEEP_OUTPUT_FILES setting
            try:
                file_manager.cleanup_output_file(result_path)
            except Exception as cleanup_error:
                logger.error(f"Error during file cleanup after callback: {cleanup_error}")

    def on_success(self, retval, task_id, args, kwargs):
        """Handle successful task completion"""
        RedisManager().update_task_status(task_id, 'completed', result=retval)
        
        # Get callback URL from task context
        callback_url = kwargs.get('callback_url')
        if callback_url and retval:
            self._send_callback(task_id, retval, callback_url)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure"""
        error = str(exc)
        RedisManager().update_task_status(task_id, 'failed', error=error)
        
        # Send error to callback URL if provided
        callback_url = kwargs.get('callback_url')
        if callback_url:
            self._send_callback(task_id, '', callback_url, error=error)

@celery.task(base=FFmpegTask, bind=True, name='app.core.processor.process_ffmpeg')
def process_ffmpeg(self, task_type: str, input_files: List[str], 
                  output_file: str, custom_params: Optional[str] = None,
                  callback_url: Optional[str] = None):
    """Process FFmpeg task"""
    processor = FFmpegProcessor()
    RedisManager().update_task_status(self.request.id, 'processing')
    
    try:
        command = processor._get_ffmpeg_command(task_type, input_files, output_file, custom_params)
        logger.info("\033[32mcommand value is: %s\033[0m", command)
        logger.info(f"Executing FFmpeg command: {' '.join(command)}")
        
        result = processor._run_ffmpeg_process(command)
        logger.info(f"FFmpeg process completed successfully")
        logger.info(f"FFmpeg stdout:\n{result.stdout}")
        logger.info(f"FFmpeg stderr:\n{result.stderr}")
        
        # Clean up input files immediately
        processor.file_manager.cleanup_input_files(input_files)
        
        # Always return the output file path - cleanup will happen after sending response
        return output_file
        
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg process failed with code {e.returncode}")
        logger.error(f"Error output:\n{e.stderr}")
        # Clean up all files on failure
        processor.file_manager.cleanup_files(input_files, output_file)
        raise
    except Exception as e:
        logger.exception("FFmpeg processing failed")
        # Clean up all files on failure
        processor.file_manager.cleanup_files(input_files, output_file)
        raise