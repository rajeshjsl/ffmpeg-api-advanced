from flask import Flask
from celery import Celery
from redis import Redis
import os

# Initialize Celery with the correct main module name
celery = Celery('app')

# Configure Celery with broker and backend
celery.conf.update({
    'broker_url': os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0'),
    'result_backend': os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/0'),
    'worker_prefetch_multiplier': 1,
    'task_track_started': True,
    'task_time_limit': int(os.environ.get('FFMPEG_TIMEOUT', '0') or 0) or None,
    'worker_max_tasks_per_child': 100,
    # Add imports configuration to ensure task discovery
    'imports': (
        'app.core.processor',
    ),
    # Add task routes if needed
    'task_routes': {
        'app.core.processor.*': {'queue': 'celery'}
    }
})

def create_app():
    """Application factory function"""
    app = Flask(__name__)
    
    # Initialize Redis
    app.redis = Redis.from_url(
        os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0'),
        decode_responses=True
    )

    # Register blueprints
    from app.routes.api import bp as api_bp
    from app.routes.monitor import bp as monitor_bp
    
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(monitor_bp, url_prefix='/queue')

    @app.route('/health')
    def health_check():
        return {
            "status": "healthy",
            "redis": app.redis.ping()
        }

    # Initialize Celery with app context
    celery.conf.update(app.config)
    
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask

    return app
