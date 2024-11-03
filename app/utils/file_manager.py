from pathlib import Path
import os
import logging
from typing import List, Union

logger = logging.getLogger(__name__)

class FileManager:
    """Manages file operations and cleanup for the FFmpeg API"""
    
    def __init__(self):
        self.temp_dir = Path('/tmp/ffmpeg_api')
        self.keep_output_files = os.getenv('KEEP_OUTPUT_FILES', 'false').lower() == 'true'
        
    def save_temp_file(self, file_path: Union[str, Path]) -> Path:
        """
        Ensures file is in the temp directory
        Returns the Path object for the file
        """
        file_path = Path(file_path)
        if not file_path.is_absolute():
            file_path = self.temp_dir / file_path
        return file_path
    
    def cleanup_input_files(self, input_files: List[Union[str, Path]]) -> None:
        """Clean up input files - they are always removed"""
        for input_file in input_files:
            try:
                input_path = self.save_temp_file(input_file)
                if input_path.exists():
                    input_path.unlink()
                    logger.info(f"Removed input file: {input_path}")
            except Exception as e:
                logger.error(f"Error removing input file {input_path}: {str(e)}")

    def cleanup_output_file(self, output_file: Union[str, Path]) -> None:
        """Clean up output file if needed"""
        if not self.keep_output_files:
            try:
                output_path = self.save_temp_file(output_file)
                if output_path.exists():
                    output_path.unlink()
                    logger.info(f"Removed output file: {output_path}")
            except Exception as e:
                logger.error(f"Error removing output file {output_path}: {str(e)}")
        else:
            logger.info(f"Keeping output file: {output_file}")
    
    def cleanup_files(self, input_files: List[Union[str, Path]], 
                     output_file: Union[str, Path]) -> None:
        """Clean up all files - used primarily for error cases"""
        self.cleanup_input_files(input_files)
        self.cleanup_output_file(output_file)