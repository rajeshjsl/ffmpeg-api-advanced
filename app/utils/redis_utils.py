from redis import Redis
import json
import time
import os
from typing import Optional, Dict, Any

class RedisManager:
    def __init__(self):
        self.redis = Redis.from_url(
            os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0'),
            decode_responses=True
        )

    def update_task_status(self, task_id: str, status: str, 
                          result: Optional[str] = None, 
                          error: Optional[str] = None) -> None:
        """Update task status and related metrics in Redis"""
        task_key = f'task:{task_id}:info'
        
        # Update task info
        update_data = {
            'status': status,
            'updated_at': time.time()
        }
        
        if result:
            update_data['result'] = result
        if error:
            update_data['error'] = error
            
        self.redis.hset(task_key, mapping=update_data)
        
        # Update task sets
        if status == 'processing':
            self.redis.sadd('queue:active', task_id)
            self.redis.srem('queue:pending', task_id)
        elif status == 'completed':
            self.redis.srem('queue:active', task_id)
            self.redis.zadd('queue:completed', {task_id: time.time()})
        elif status == 'failed':
            self.redis.srem('queue:active', task_id)
            self.redis.hset('queue:failed', task_id, error or 'Unknown error')

    def get_queue_stats(self) -> Dict[str, Any]:
        """Get current queue statistics"""
        active_tasks = self.redis.scard('queue:active')
        pending_tasks = self.redis.llen('queue:pending')
        
        now = time.time()
        day_ago = now - 86400
        recent_completions = self.redis.zcount('queue:completed', day_ago, now)
        
        return {
            'active_tasks': active_tasks,
            'pending_tasks': pending_tasks,
            'recent_completions': recent_completions,
            'recent_failures': self.redis.hlen('queue:failed'),
        }

    def get_task_info(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed task information"""
        task_info = self.redis.hgetall(f'task:{task_id}:info')
        return task_info if task_info else None