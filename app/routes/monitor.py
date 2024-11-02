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

@bp.route('/task/<task_id>')
def get_task_details(task_id):
    """Get detailed information about a specific task"""
    task_info = redis_manager.get_task_info(task_id)
    if not task_info:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify(task_info)