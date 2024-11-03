from flask import Flask, request
from celery import Celery
from redis import Redis
import os
import logging
from logging.config import dictConfig

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

# Add logging configuration before creating the app
dictConfig({
    'version': 1,
    'formatters': {
        'default': {
            'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
            'formatter': 'default'
        }
    },
    'root': {
        'level': 'INFO',
        'handlers': ['console']
    },
    'loggers': {
        'app': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': False
        },
        'gunicorn.error': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': False
        }
    }
})

def create_app():
    """Application factory function"""
    app = Flask(__name__)

    # Enable logging of all requests
    @app.before_request
    def log_request_info():
        if request.method == 'POST':  # Only log POST requests
            app.logger.info('Headers: %s', dict(request.headers))
            app.logger.info('Files: %s', list(request.files.keys()) if request.files else None)
            app.logger.info('Form Data Keys: %s', list(request.form.keys()) if request.form else None)
    
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
