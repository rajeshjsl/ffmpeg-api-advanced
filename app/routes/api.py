from flask import Blueprint, request, jsonify, current_app, send_file
from werkzeug.utils import secure_filename
import os
from pathlib import Path
import uuid
import mimetypes
import logging
from app.core.processor import process_ffmpeg
from app.utils.redis_utils import RedisManager
from app.utils.file_manager import FileManager

logger = logging.getLogger(__name__)

bp = Blueprint('api', __name__)
redis_manager = RedisManager()
file_manager = FileManager()

def send_file_and_cleanup(file_path: str, mime_type: str, download_name: str):
    """Helper function to send file and handle cleanup"""
    try:
        response = send_file(
            file_path,
            mimetype=mime_type,
            as_attachment=True,
            download_name=download_name
        )
        
        response.headers['Content-Type'] = mime_type
        response.headers['X-Filename'] = download_name
        
        # Call after_this_request to ensure cleanup happens after response is sent
        def cleanup(response):
            file_manager.cleanup_output_file(file_path)
            return response
            
        if not file_manager.keep_output_files:
            from flask import after_this_request
            after_this_request(cleanup)
            
        return response
    except Exception as e:
        # Clean up on error
        file_manager.cleanup_output_file(file_path)
        raise

def save_uploaded_file(file, prefix: str) -> Path:
    """Save uploaded file with secure name"""
    filename = secure_filename(file.filename)
    temp_id = str(uuid.uuid4())
    temp_path = Path('/tmp/ffmpeg_api') / f"{prefix}_{temp_id}_{filename}"
    file.save(str(temp_path))
    return temp_path

@bp.route('/captionize', methods=['POST'])
def captionize_video():
    """Add subtitles to video"""
    logger.info("Received captionize request")
    
    # Log request details
    logger.info(f"Files received: {list(request.files.keys())}")
    logger.info(f"Form data: {list(request.form.keys())}")
    
    if 'input_video_file' not in request.files or 'input_ass_file' not in request.files:
        return jsonify({
            "error": "Both video and ASS subtitle files are required",
            "details": "Use 'input_video_file' for video and 'input_ass_file' for ASS subtitle file. Note: Only .ass subtitle files are supported."
        }), 400
        
    video_file = request.files['input_video_file']
    subtitle_file = request.files['input_ass_file']
    
    # Validate file names
    if video_file.filename == '':
        return jsonify({"error": "No video file selected"}), 400
    if subtitle_file.filename == '':
        return jsonify({"error": "No ASS subtitle file selected"}), 400

    # Validate subtitle file extension
    if not subtitle_file.filename.lower().endswith('.ass'):
        return jsonify({
            "error": "Invalid subtitle file format",
            "details": "Only .ass subtitle files are supported. Other formats like .srt, .vtt, etc. are not supported."
        }), 400

    callback_url = request.form.get('callback_url')
    custom_command = request.form.get('custom_command')
    if custom_command and ('{video}' not in custom_command or '{subtitle}' not in custom_command):
        return jsonify({
            "error": "Invalid custom command",
            "details": "Custom command must contain both '{video}' and '{subtitle}' placeholders. Example: -i {video} -vf subtitles={subtitle} -c:a copy"
        }), 400
    
    # Save uploaded files with appropriate prefixes
    video_path = save_uploaded_file(video_file, 'video')
    subtitle_path = save_uploaded_file(subtitle_file, 'sub')
    output_path = video_path.parent / f"captionized_{uuid.uuid4()}_{video_path.name}"

    # Start processing task
    task = process_ffmpeg.delay(
        'captionize',
        [str(video_path), str(subtitle_path)],
        str(output_path),
        custom_command,
        callback_url=callback_url
    )

    logger.info(f"Started captionize task {task.id} for files: video={video_file.filename}, sub={subtitle_file.filename}")
    
    if callback_url:
        response = {
            'task_id': task.id,
            'status': 'processing',
            'status_url': f'/queue/task/{task.id}'
        }
        logger.info(f"Returning async response for task {task.id}")
        return jsonify(response), 202
        
    # Wait for result if no callback
    try:
        ffmpeg_timeout = int(os.getenv('FFMPEG_TIMEOUT', '0'))
        result = task.get(timeout=None if ffmpeg_timeout == 0 else ffmpeg_timeout)
        
        mime_type, _ = mimetypes.guess_type(output_path)
        if not mime_type:
            mime_type = 'video/mp4'
            
        return send_file_and_cleanup(
            result,
            mime_type,
            f"captionized_{video_file.filename}"
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/normalize', methods=['POST'])
def normalize_audio():
    """Normalize audio levels in video/audio file"""
    if 'input_file' not in request.files:
        return jsonify({
            "error": "Input file is required",
            "details": "Use 'input_file' parameter to upload video or audio file"
        }), 400
        
    input_file = request.files['input_file']
    
    if input_file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    callback_url = request.form.get('callback_url')
    custom_command = request.form.get('custom_command')
    if custom_command and '{input}' not in custom_command:
        return jsonify({
            "error": "Invalid custom command",
            "details": "Custom command must contain '{input}' placeholder. Example: -i {input} -filter:a volume=2.0"
        }), 400
    
    # Save uploaded file
    input_path = save_uploaded_file(input_file, 'input')
    output_path = input_path.parent / f"normalized_{uuid.uuid4()}_{input_path.name}"
    
    # Start processing task
    task = process_ffmpeg.delay(
        'normalize',
        [str(input_path)],
        str(output_path),
        custom_command,
        callback_url=callback_url
    )
    
    if callback_url:
        return jsonify({
            'task_id': task.id,
            'status': 'processing',
            'status_url': f'/queue/task/{task.id}'
        }), 202
        
    # Wait for result if no callback
    try:
        ffmpeg_timeout = int(os.getenv('FFMPEG_TIMEOUT', '0'))
        result = task.get(timeout=None if ffmpeg_timeout == 0 else ffmpeg_timeout)
        
        mime_type, _ = mimetypes.guess_type(output_path)
        if not mime_type:
            mime_type = 'video/mp4' if output_path.suffix in ['.mp4', '.mov'] else 'audio/mpeg'
            
        return send_file_and_cleanup(
            result,
            mime_type,
            f"normalized_{input_file.filename}"
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/custom', methods=['POST'])
def custom_ffmpeg():
    """
    Custom FFmpeg processing supporting multiple input files.
    Files should be uploaded with incrementing indices:
    input_video[0], input_video[1], input_audio[0], input_audio[1], etc.
    """
    if not request.files:
        return jsonify({
            "error": "No input files provided",
            "details": "Provide input files with indexed names: input_video[0], input_video[1], input_audio[0], etc."
        }), 400
        
    if 'custom_command' not in request.form:
        return jsonify({
            "error": "No FFmpeg command provided",
            "details": "Provide FFmpeg parameters in 'custom_command'. Use {video0}, {video1}, {audio0}, etc. as placeholders."
        }), 400

    # Extract and validate files
    input_files = {}
    file_paths = {}
    
    # Process all uploaded files
    for key in request.files:
        file = request.files[key]
        if file.filename == '':
            continue
            
        # Save file with appropriate prefix
        if key.startswith('input_video'):
            prefix = 'video'
            type_key = 'video'
        elif key.startswith('input_audio'):
            prefix = 'audio'
            type_key = 'audio'
        else:
            continue
            
        try:
            idx = int(key[key.index('[')+1:key.index(']')])
            saved_path = save_uploaded_file(file, f"{prefix}{idx}")
            file_paths[f"{type_key}{idx}"] = str(saved_path)
            input_files[key] = saved_path
        except (ValueError, IndexError):
            return jsonify({
                "error": "Invalid file parameter format",
                "details": "Use format: input_video[0], input_video[1], input_audio[0], etc."
            }), 400

    if not input_files:
        return jsonify({"error": "No valid input files provided"}), 400

    # Create output path
    first_input = list(input_files.values())[0]
    output_path = first_input.parent / f"output_{uuid.uuid4()}_{first_input.name}"

    # Get custom command and replace placeholders
    custom_command = request.form['custom_command']
    for key, path in file_paths.items():
        custom_command = custom_command.replace(f"{{{key}}}", path)

    callback_url = request.form.get('callback_url')
    ffmpeg_timeout = int(os.getenv('FFMPEG_TIMEOUT', '0'))

    # Start processing task with callback URL
    task = process_ffmpeg.delay(
        'custom',
        list(file_paths.values()),
        str(output_path),
        custom_command,
        callback_url=callback_url  # Pass callback URL to task
    )
    
    return jsonify({
        'task_id': task.id,
        'status': 'processing',
        'status_url': f'/queue/task/{task.id}'
    }), 202