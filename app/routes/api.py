from flask import Blueprint, request, jsonify, current_app, send_file
from werkzeug.utils import secure_filename
import os
from pathlib import Path
import uuid
import mimetypes
from app.core.processor import process_ffmpeg
from app.utils.redis_utils import RedisManager

bp = Blueprint('api', __name__)
redis_manager = RedisManager()

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
    # Check for required files with clearer parameter names
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
    
    # Save uploaded files with appropriate prefixes
    video_path = save_uploaded_file(video_file, 'video')
    subtitle_path = save_uploaded_file(subtitle_file, 'sub')
    output_path = video_path.parent / f"output_{uuid.uuid4()}_{video_path.name}"
    
    # Start processing task
    task = process_ffmpeg.delay(
        'captionize',
        [str(video_path), str(subtitle_path)],
        str(output_path),
        custom_command
    )
    
    if callback_url:
        return jsonify({
            'task_id': task.id,
            'status': 'processing',
            'status_url': f'/queue/task/{task.id}'
        }), 202
        
    # Wait for result if no callback
    try:
        result = task.get(timeout=int(os.getenv('FFMPEG_TIMEOUT', '0') or 600))
        
        # Determine mime type
        mime_type, _ = mimetypes.guess_type(output_path)
        if not mime_type:
            mime_type = 'video/mp4'
            
        response = send_file(
            result,
            mimetype=mime_type,
            as_attachment=True,
            download_name=f"captioned_{video_file.filename}"
        )
        
        # Set additional headers
        response.headers['Content-Type'] = mime_type
        response.headers['X-Filename'] = f"captioned_{video_file.filename}"
        
        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/normalize', methods=['POST'])
def normalize_audio():
    """Normalize audio levels"""
    if 'input' not in request.files:
        return jsonify({'error': 'Missing input file'}), 400
        
    input_file = request.files['input']
    callback_url = request.form.get('callback_url')
    custom_params = request.form.get('custom_command')
    
    # Save uploaded file
    input_path = save_uploaded_file(input_file, 'input')
    output_path = input_path.parent / f"normalized_{uuid.uuid4()}_{input_path.name}"
    
    # Start processing task
    task = process_ffmpeg.delay(
        'normalize',
        [str(input_path)],
        str(output_path),
        custom_params
    )
    
    if callback_url:
        return jsonify({
            'task_id': task.id,
            'status': 'processing',
            'status_url': f'/queue/task/{task.id}'
        }), 202
        
    # Wait for result if no callback
    try:
        result = task.get(timeout=int(os.getenv('FFMPEG_TIMEOUT', '0') or 600))
        
        # Determine mime type
        mime_type, _ = mimetypes.guess_type(output_path)
        if not mime_type:
            mime_type = 'video/mp4' if output_path.suffix in ['.mp4', '.mov'] else 'audio/mpeg'
            
        return send_file(
            result,
            mimetype=mime_type,
            as_attachment=True,
            download_name=f"normalized_{input_file.filename}"
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/custom', methods=['POST'])
def custom_ffmpeg():
    """Custom FFmpeg processing"""
    if not request.files:
        return jsonify({'error': 'No input files provided'}), 400
        
    if 'custom_command' not in request.form:
        return jsonify({'error': 'No FFmpeg command provided'}), 400
        
    callback_url = request.form.get('callback_url')
    custom_params = request.form['custom_command']
    
    # Save all uploaded files
    input_files = []
    for key in request.files:
        file_path = save_uploaded_file(request.files[key], f'input_{key}')
        input_files.append(str(file_path))
        
    # Create output path
    first_input = Path(input_files[0])
    output_path = first_input.parent / f"output_{uuid.uuid4()}_{first_input.name}"
    
    # Start processing task
    task = process_ffmpeg.delay(
        'custom',
        input_files,
        str(output_path),
        custom_params
    )
    
    if callback_url:
        return jsonify({
            'task_id': task.id,
            'status': 'processing',
            'status_url': f'/queue/task/{task.id}'
        }), 202
        
    # Wait for result if no callback
    try:
        result = task.get(timeout=int(os.getenv('FFMPEG_TIMEOUT', '0') or 600))
        
        # Determine mime type
        mime_type, _ = mimetypes.guess_type(output_path)
        if not mime_type:
            mime_type = 'video/mp4'
            
        return send_file(
            result,
            mimetype=mime_type,
            as_attachment=True,
            download_name=f"output_{first_input.name}"
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500