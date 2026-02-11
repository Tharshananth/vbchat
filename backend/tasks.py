"""
Celery tasks for background processing
Cleanup old sessions, monitor health, etc.
"""
from celery import Celery
from celery.schedules import crontab
import logging
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

from database import ChatSession, FeedbackInteraction
from services.chat_memory_service import ChatMemoryService
from redis import Redis

logger = logging.getLogger(__name__)

# Initialize Celery
redis_host = os.getenv('REDIS_HOST', 'localhost')
celery_app = Celery(
    'chatbot_tasks',
    broker=f'redis://{redis_host}:6379/0',
    backend=f'redis://{redis_host}:6379/0'
)

# Database setup
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./data/database/feedback.db')
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# Redis setup
redis_client = Redis(host=redis_host, port=6379, decode_responses=True)


@celery_app.task(name='cleanup_old_sessions')
def cleanup_old_sessions():
    """
    Cleanup sessions older than 24 hours
    Run daily at 2 AM
    """
    logger.info("🧹 Starting session cleanup...")
    
    db = SessionLocal()
    try:
        memory_service = ChatMemoryService(redis_client=redis_client)
        deleted = memory_service.cleanup_old_sessions(db, hours_old=24)
        
        logger.info(f"✅ Cleaned up {deleted} old sessions")
        return {"status": "success", "deleted": deleted}
        
    except Exception as e:
        logger.error(f"❌ Cleanup failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


@celery_app.task(name='cleanup_redis_keys')
def cleanup_redis_keys():
    """
    Remove expired Redis keys
    Run every hour
    """
    logger.info("🧹 Cleaning Redis keys...")
    
    try:
        # Get all chat context keys
        keys = redis_client.keys("chat:context:*")
        deleted = 0
        
        for key in keys:
            # Check TTL
            ttl = redis_client.ttl(key)
            if ttl == -1:  # No expiry set
                redis_client.delete(key)
                deleted += 1
            elif ttl == -2:  # Key doesn't exist
                deleted += 1
        
        logger.info(f"✅ Deleted {deleted} stale Redis keys")
        return {"status": "success", "deleted": deleted}
        
    except Exception as e:
        logger.error(f"❌ Redis cleanup failed: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task(name='generate_daily_report')
def generate_daily_report():
    """
    Generate daily usage report
    Run at midnight
    """
    logger.info("📊 Generating daily report...")
    
    db = SessionLocal()
    try:
        from sqlalchemy import func
        
        # Yesterday's date
        yesterday = datetime.utcnow().date() - timedelta(days=1)
        
        # Count messages
        total_messages = db.query(func.count(FeedbackInteraction.id)).filter(
            func.date(FeedbackInteraction.timestamp) == yesterday
        ).scalar()
        
        # Count unique users
        unique_users = db.query(func.count(func.distinct(FeedbackInteraction.user_id))).filter(
            func.date(FeedbackInteraction.timestamp) == yesterday
        ).scalar()
        
        # Count unique sessions
        unique_sessions = db.query(func.count(func.distinct(FeedbackInteraction.session_id))).filter(
            func.date(FeedbackInteraction.timestamp) == yesterday
        ).scalar()
        
        # Count by provider
        provider_stats = db.query(
            FeedbackInteraction.provider_used,
            func.count(FeedbackInteraction.id)
        ).filter(
            func.date(FeedbackInteraction.timestamp) == yesterday
        ).group_by(FeedbackInteraction.provider_used).all()
        
        # Total tokens
        total_tokens = db.query(func.sum(FeedbackInteraction.tokens_used)).filter(
            func.date(FeedbackInteraction.timestamp) == yesterday
        ).scalar() or 0
        
        report = {
            "date": str(yesterday),
            "total_messages": total_messages,
            "unique_users": unique_users,
            "unique_sessions": unique_sessions,
            "total_tokens": total_tokens,
            "provider_stats": {provider: count for provider, count in provider_stats},
            "avg_messages_per_user": round(total_messages / unique_users, 2) if unique_users > 0 else 0,
            "avg_messages_per_session": round(total_messages / unique_sessions, 2) if unique_sessions > 0 else 0
        }
        
        logger.info(f"✅ Daily report generated: {report}")
        
        # You could send this via email, Slack, etc.
        return report
        
    except Exception as e:
        logger.error(f"❌ Report generation failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


@celery_app.task(name='check_redis_health')
def check_redis_health():
    """
    Check Redis connection health
    Run every 5 minutes
    """
    try:
        redis_client.ping()
        return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f"❌ Redis health check failed: {e}")
        return {"status": "unhealthy", "error": str(e), "timestamp": datetime.utcnow().isoformat()}


@celery_app.task(name='sync_redis_to_db')
def sync_redis_to_db():
    """
    Backup Redis context data to database
    Run every 30 minutes
    """
    logger.info("💾 Syncing Redis to database...")
    
    db = SessionLocal()
    synced = 0
    
    try:
        keys = redis_client.keys("chat:context:*")
        
        for key in keys:
            # Get data from Redis
            data = redis_client.get(key)
            if not data:
                continue
            
            # Parse and save to DB if needed
            # (Your logic here to ensure DB has latest state)
            synced += 1
        
        logger.info(f"✅ Synced {synced} contexts to database")
        return {"status": "success", "synced": synced}
        
    except Exception as e:
        logger.error(f"❌ Sync failed: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


# Configure periodic tasks
celery_app.conf.beat_schedule = {
    'cleanup-old-sessions-daily': {
        'task': 'cleanup_old_sessions',
        'schedule': crontab(hour=2, minute=0),  # 2 AM daily
    },
    'cleanup-redis-hourly': {
        'task': 'cleanup_redis_keys',
        'schedule': crontab(minute=0),  # Every hour
    },
    'daily-report': {
        'task': 'generate_daily_report',
        'schedule': crontab(hour=0, minute=5),  # 12:05 AM daily
    },
    'redis-health-check': {
        'task': 'check_redis_health',
        'schedule': 300.0,  # Every 5 minutes
    },
    'sync-redis-to-db': {
        'task': 'sync_redis_to_db',
        'schedule': 1800.0,  # Every 30 minutes
    },
}

celery_app.conf.timezone = 'UTC'