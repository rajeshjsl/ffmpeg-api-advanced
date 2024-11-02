from flask import Blueprint, jsonify, request, current_app
from app.utils.redis_utils import RedisManager

bp = Blueprint('monitor', __name__)
redis_manager = RedisManager()

@bp.route('/status')
def get_queue_status():
    """Get current queue status"""
    stats = redis_manager.get_queue_stats()
    return jsonify(stats)

@bp.route('/tasks')
def get_tasks():
    """Get list of tasks with pagination"""
    status = request.args.get('status', 'all')
    limit = min(int(request.args.get('limit', 20)), 100)
    offset = int(request.args.get('offset', 0))
    
    tasks = redis_manager.get_tasks(status, limit, offset)
    return jsonify(tasks)

@bp.route('/task/<task_id>/file')
def get_task_file_status(task_id):
    """Get status of file processing and delivery for a specific task"""
    task_info = redis_manager.get_task_info(task_id)
    if not task_info:
        return jsonify({'error': 'Task not found'}), 404
        
    file_info = {
        'task_id': task_id,
        'status': task_info.get('status'),
        'result_file': task_info.get('result'),
        'callback_status': task_info.get('callback_status'),
        'callback_timestamp': task_info.get('callback_timestamp'),
        'error': task_info.get('error')
    }
    
    return jsonify(file_info)