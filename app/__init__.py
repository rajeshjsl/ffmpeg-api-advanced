from flask import Flask
from celery import Celery
from redis import Redis
import os

# Initialize Celery
celery = Celery('ffmpeg_tasks')
celery.conf.broker_url = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
celery.conf.result_backend = os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')

def create_app():
    """Application factory function"""
    app = Flask(__name__)
    
    # Initialize Redis
    app.redis = Redis.from_url(
        os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0'),
        decode_responses=True  # Auto-decode Redis responses to strings
    )

    # Register blueprints
    from app.routes.api import bp as api_bp
    from app.routes.monitor import bp as monitor_bp
    
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(monitor_bp, url_prefix='/queue')

    # Health check endpoint
    @app.route('/health')
    def health_check():
        return {
            "status": "healthy",
            "redis": app.redis.ping()
        }

    return app

# Create the Celery instance
celery.conf.update({
    'worker_prefetch_multiplier': 1,  # Disable prefetching for fair task distribution
    'task_track_started': True,       # Enable tracking of task start time
    'task_time_limit': int(os.environ.get('FFMPEG_TIMEOUT', '0') or 0) or None,  # Task timeout
    'worker_max_tasks_per_child': 100  # Restart workers after 100 tasks
})

app = create_app()