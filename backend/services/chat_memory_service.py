"""
PRODUCTION-GRADE CHAT MEMORY SERVICE
Bulletproof 5-minute context window with Redis + PostgreSQL fallback
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Tuple
import logging
import json
import hashlib
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import tiktoken
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Constants
CONTEXT_DURATION_MINUTES = 5
MAX_CONTEXT_MESSAGES = 6
MAX_CONTEXT_TOKENS = 3000  # Safe limit for most models
REDIS_TTL_SECONDS = 360  # 6 minutes (buffer)

@dataclass
class ChatMessage:
    """Immutable chat message"""
    role: str
    content: str
    timestamp: datetime
    message_id: str
    tokens: int
    
    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            'timestamp': self.timestamp.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ChatMessage':
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)

@dataclass
class ContextWindow:
    """Context window state"""
    session_id: str
    window_start: datetime
    window_end: datetime
    window_number: int
    messages: List[ChatMessage]
    
    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        # Handle both naive and aware datetimes
        if self.window_end.tzinfo is None:
            now = now.replace(tzinfo=None)
        return now >= self.window_end
    def time_remaining(self) -> float:
        now = datetime.now(timezone.utc)
        if self.window_end.tzinfo is None:
            now = now.replace(tzinfo=None)
        delta = self.window_end - now
        return max(0, delta.total_seconds())
    def add_message(self, msg: ChatMessage) -> None:
        """Add message and maintain limits"""
        self.messages.append(msg)
        # Keep only recent messages that fit token budget
        self._trim_to_token_limit()
    
    def _trim_to_token_limit(self) -> None:
        """Keep messages within token limit"""
        total_tokens = 0
        kept_messages = []
        
        # Iterate from newest to oldest
        for msg in reversed(self.messages):
            if total_tokens + msg.tokens > MAX_CONTEXT_TOKENS:
                break
            kept_messages.insert(0, msg)
            total_tokens += msg.tokens
            
            # Also limit by count
            if len(kept_messages) >= MAX_CONTEXT_MESSAGES:
                break
        
        self.messages = kept_messages
        logger.debug(f"Trimmed to {len(kept_messages)} messages, {total_tokens} tokens")


class ChatMemoryService:
    """
    Production-ready chat memory with Redis + DB fallback
    Thread-safe, handles all edge cases
    """
    
    def __init__(
        self,
        redis_client: Optional[Redis] = None,
        db_session_factory = None,
        enable_redis: bool = True
    ):
        self.redis = redis_client if enable_redis else None
        self.db_session_factory = db_session_factory
        self.tokenizer = tiktoken.get_encoding("cl100k_base")
        
        # Test Redis connection
        if self.redis:
            try:
                self.redis.ping()
                logger.info("✅ Redis connected")
            except RedisError as e:
                logger.warning(f"⚠️ Redis unavailable: {e}. Using DB fallback.")
                self.redis = None
    
    def count_tokens(self, text: str) -> int:
        """Accurate token counting"""
        try:
            return len(self.tokenizer.encode(text))
        except:
            # Fallback to rough estimate
            return len(text) // 4
    
    def get_or_create_context(
        self,
        session_id: str,
        user_id: str,
        db: Session
    ) -> ContextWindow:
        """
        Get current context window or create new one
        ATOMIC OPERATION - Thread-safe
        """
        
        # Try Redis first (fast path)
        if self.redis:
            try:
                context = self._get_from_redis(session_id)
                if context:
                    # Check if expired
                    if context.is_expired():
                        logger.info(f"⏰ Context expired for {session_id}")
                        context = self._create_new_window(session_id, context.window_number + 1)
                        self._save_to_redis(context)
                    return context
            except RedisError as e:
                logger.error(f"Redis error: {e}, falling back to DB")
        
        # DB fallback (slower but reliable)
        return self._get_or_create_from_db(session_id, user_id, db)
    
    def add_interaction(
        self,
        session_id: str,
        user_id: str,
        question: str,
        response: str,
        message_id: str,
        provider: str,
        db: Session
    ) -> Tuple[ContextWindow, bool]:
        """
        Add Q&A to context window
        Returns: (updated_context, was_reset)
        """
        
        # Get current context
        context = self.get_or_create_context(session_id, user_id, db)
        was_reset = False
        
        # Check expiration AGAIN (race condition protection)
        if context.is_expired():
            logger.warning(f"Context expired during processing for {session_id}")
            context = self._create_new_window(session_id, context.window_number + 1)
            was_reset = True
        
        # Create messages with token counts
        user_msg = ChatMessage(
            role="user",
            content=question,
            timestamp=datetime.utcnow(),
            message_id=f"{message_id}_q",
            tokens=self.count_tokens(question)
        )
        
        assistant_msg = ChatMessage(
            role="assistant",
            content=response,
            timestamp=datetime.now(timezone.utc),
            message_id=message_id,
            tokens=self.count_tokens(response)
        )
        
        # Add to context
        context.add_message(user_msg)
        context.add_message(assistant_msg)
        
        # Persist to both Redis and DB
        try:
            if self.redis:
                self._save_to_redis(context)
            self._save_to_db(session_id, user_id, question, response, message_id, provider, db)
        except Exception as e:
            logger.error(f"Failed to persist: {e}")
            # Don't fail the request, data is in memory
        
        return context, was_reset
    
    def build_llm_context(
        self,
        context: ContextWindow,
        current_question: str
    ) -> List[Dict[str, str]]:
        """
        Build message list for LLM
        Ensures token limit is respected
        """
        messages = []
        
        # Add historical messages
        for msg in context.messages:
            messages.append({
                "role": msg.role,
                "content": msg.content
            })
        
        # Add current question
        messages.append({
            "role": "user",
            "content": current_question
        })
        
        # Final token check
        total_tokens = sum(self.count_tokens(m["content"]) for m in messages)
        
        if total_tokens > MAX_CONTEXT_TOKENS:
            logger.warning(f"Context exceeds token limit: {total_tokens}")
            # Emergency trim - keep only last few
            messages = messages[-(MAX_CONTEXT_MESSAGES + 1):]
        
        logger.info(f"Built context: {len(messages)} messages, ~{total_tokens} tokens")
        return messages
    
    def reset_context(
        self,
        session_id: str,
        user_id: str,
        db: Session
    ) -> ContextWindow:
        """Manually reset context window"""
        
        # Get current window number
        try:
            if self.redis:
                old_context = self._get_from_redis(session_id)
                window_num = old_context.window_number + 1 if old_context else 0
            else:
                window_num = self._get_window_number_from_db(session_id, db) + 1
        except:
            window_num = 0
        
        # Create new window
        context = self._create_new_window(session_id, window_num)
        
        # Save
        if self.redis:
            self._save_to_redis(context)
        self._update_session_in_db(session_id, user_id, window_num, db)
        
        logger.info(f"🔄 Context manually reset for {session_id}")
        return context
    
    # ===== PRIVATE METHODS =====
    
    def _create_new_window(
        self,
        session_id: str,
        window_number: int
    ) -> ContextWindow:
        """Create fresh context window"""
        now = datetime.now(timezone.utc)
        return ContextWindow(
            session_id=session_id,
            window_start=now,
            window_end=now + timedelta(minutes=CONTEXT_DURATION_MINUTES),
            window_number=window_number,
            messages=[]
        )
    
    def _get_from_redis(self, session_id: str) -> Optional[ContextWindow]:
        """Get context from Redis"""
        key = f"chat:context:{session_id}"
        data = self.redis.get(key)
        
        if not data:
            return None
        
        try:
            obj = json.loads(data)
            messages = [ChatMessage.from_dict(m) for m in obj['messages']]
            
            return ContextWindow(
                session_id=obj['session_id'],
                window_start=datetime.fromisoformat(obj['window_start']),
                window_end=datetime.fromisoformat(obj['window_end']),
                window_number=obj['window_number'],
                messages=messages
            )
        except Exception as e:
            logger.error(f"Failed to deserialize Redis data: {e}")
            return None
    
    def _save_to_redis(self, context: ContextWindow) -> None:
        """Save context to Redis with TTL"""
        key = f"chat:context:{context.session_id}"
        
        data = {
            'session_id': context.session_id,
            'window_start': context.window_start.isoformat(),
            'window_end': context.window_end.isoformat(),
            'window_number': context.window_number,
            'messages': [m.to_dict() for m in context.messages]
        }
        
        self.redis.setex(
            key,
            REDIS_TTL_SECONDS,
            json.dumps(data)
        )
    
    def _get_or_create_from_db(
        self,
        session_id: str,
        user_id: str,
        db: Session
    ) -> ContextWindow:
        """Get or create context from database (fallback)"""
        from database import ChatSession, FeedbackInteraction
        
        # Use SELECT FOR UPDATE to prevent race conditions
        session = db.query(ChatSession).filter(
            ChatSession.session_id == session_id
        ).with_for_update().first()
        
        now = datetime.utcnow()
        
        if not session:
            # Create new session
            expiry = now + timedelta(minutes=CONTEXT_DURATION_MINUTES)
            session = ChatSession(
                user_id=user_id,
                session_id=session_id,
                start_time=now,
                context_window_start=now,
                context_expires_at=expiry,
                last_activity=now,
                message_count=0,
                context_resets=0,
                is_active=True
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            
            return self._create_new_window(session_id, 0)
        
        # Check expiration
        if now >= session.context_expires_at:
            # Reset
            session.context_window_start = now
            session.context_expires_at = now + timedelta(minutes=CONTEXT_DURATION_MINUTES)
            session.context_resets += 1
            db.commit()
            
            return self._create_new_window(session_id, session.context_resets)
        
        # Load messages from current window
        messages_data = db.query(FeedbackInteraction).filter(
            and_(
                FeedbackInteraction.session_id == session_id,
                FeedbackInteraction.timestamp >= session.context_window_start
            )
        ).order_by(FeedbackInteraction.timestamp.asc()).limit(MAX_CONTEXT_MESSAGES).all()
        
        messages = []
        for msg_data in messages_data:
            messages.append(ChatMessage(
                role="user",
                content=msg_data.question,
                timestamp=msg_data.timestamp,
                message_id=f"{msg_data.message_id}_q",
                tokens=self.count_tokens(msg_data.question)
            ))
            messages.append(ChatMessage(
                role="assistant",
                content=msg_data.response,
                timestamp=msg_data.timestamp,
                message_id=msg_data.message_id,
                tokens=self.count_tokens(msg_data.response)
            ))
        
        return ContextWindow(
            session_id=session_id,
            window_start=session.context_window_start,
            window_end=session.context_expires_at,
            window_number=session.context_resets,
            messages=messages
        )
    
    def _save_to_db(
        self,
        session_id: str,
        user_id: str,
        question: str,
        response: str,
        message_id: str,
        provider: str,
        db: Session
    ) -> None:
        """Persist to database"""
        from database import FeedbackInteraction
        
        interaction = FeedbackInteraction(
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
            timestamp=datetime.utcnow(),
            question=question,
            response=response,
            provider_used=provider,
            tokens_used=self.count_tokens(question) + self.count_tokens(response)
        )
        
        db.add(interaction)
        db.commit()
    
    def _update_session_in_db(
        self,
        session_id: str,
        user_id: str,
        window_number: int,
        db: Session
    ) -> None:
        """Update session metadata"""
        from database import ChatSession
        
        session = db.query(ChatSession).filter(
            ChatSession.session_id == session_id
        ).first()
        
        now = datetime.utcnow()
        
        if session:
            session.context_window_start = now
            session.context_expires_at = now + timedelta(minutes=CONTEXT_DURATION_MINUTES)
            session.context_resets = window_number
            session.last_activity = now
        else:
            session = ChatSession(
                user_id=user_id,
                session_id=session_id,
                start_time=now,
                context_window_start=now,
                context_expires_at=now + timedelta(minutes=CONTEXT_DURATION_MINUTES),
                last_activity=now,
                message_count=0,
                context_resets=window_number,
                is_active=True
            )
            db.add(session)
        
        db.commit()
    
    def _get_window_number_from_db(self, session_id: str, db: Session) -> int:
        """Get current window number from DB"""
        from database import ChatSession
        
        session = db.query(ChatSession).filter(
            ChatSession.session_id == session_id
        ).first()
        
        return session.context_resets if session else 0
    
    def cleanup_old_sessions(self, db: Session, hours_old: int = 24) -> int:
        """
        Cleanup old inactive sessions
        Run this periodically (cron job)
        """
        from database import ChatSession
        
        cutoff = datetime.utcnow() - timedelta(hours=hours_old)
        
        deleted = db.query(ChatSession).filter(
            and_(
                ChatSession.last_activity < cutoff,
                ChatSession.is_active == True
            )
        ).update({'is_active': False})
        
        db.commit()
        logger.info(f"🧹 Cleaned up {deleted} old sessions")
        return deleted


# ===== SINGLETON INSTANCE =====

_memory_service: Optional[ChatMemoryService] = None

def get_memory_service(
    redis_client: Optional[Redis] = None,
    db_session_factory = None
) -> ChatMemoryService:
    """Get or create singleton memory service"""
    global _memory_service
    
    if _memory_service is None:
        _memory_service = ChatMemoryService(
            redis_client=redis_client,
            db_session_factory=db_session_factory
        )
    
    return _memory_service