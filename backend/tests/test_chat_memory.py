"""
COMPREHENSIVE TESTS FOR CHAT MEMORY
Tests all edge cases, race conditions, failures
"""
import pytest
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock
from concurrent.futures import ThreadPoolExecutor
import uuid

from services.chat_memory_service import (
    ChatMemoryService,
    ChatMessage,
    ContextWindow,
    CONTEXT_DURATION_MINUTES,
    MAX_CONTEXT_TOKENS
)


class TestChatMessage:
    """Test ChatMessage dataclass"""
    
    def test_create_message(self):
        msg = ChatMessage(
            role="user",
            content="Hello",
            timestamp=datetime.now(timezone.utc),
            message_id="msg_123",
            tokens=5
        )
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.tokens == 5
    
    def test_to_dict(self):
        msg = ChatMessage(
            role="user",
            content="Hello",
            timestamp=datetime.now(timezone.utc),
            message_id="msg_123",
            tokens=5
        )
        d = msg.to_dict()
        assert d['role'] == "user"
        assert 'timestamp' in d
    
    def test_from_dict(self):
        msg = ChatMessage(
            role="user",
            content="Hello",
            timestamp=datetime.now(timezone.utc),
            message_id="msg_123",
            tokens=5
        )
        d = msg.to_dict()
        restored = ChatMessage.from_dict(d)
        assert restored.role == msg.role
        assert restored.content == msg.content


class TestContextWindow:
    """Test ContextWindow logic"""
    
    def test_create_window(self):
        now = datetime.now(timezone.utc)
        window = ContextWindow(
            session_id="sess_123",
            window_start=now,
            window_end=now + timedelta(minutes=5),
            window_number=0,
            messages=[]
        )
        assert window.session_id == "sess_123"
        assert window.window_number == 0
        assert len(window.messages) == 0
    
    def test_is_expired_false(self):
        now = datetime.now(timezone.utc)
        window = ContextWindow(
            session_id="sess_123",
            window_start=now,
            window_end=now + timedelta(minutes=5),
            window_number=0,
            messages=[]
        )
        assert not window.is_expired()
    
    def test_is_expired_true(self):
        now = datetime.now(timezone.utc)
        window = ContextWindow(
            session_id="sess_123",
            window_start=now - timedelta(minutes=10),
            window_end=now - timedelta(minutes=5),
            window_number=0,
            messages=[]
        )
        assert window.is_expired()
    
    def test_time_remaining(self):
        now = datetime.now(timezone.utc)
        window = ContextWindow(
            session_id="sess_123",
            window_start=now,
            window_end=now + timedelta(seconds=100),
            window_number=0,
            messages=[]
        )
        remaining = window.time_remaining()
        assert 95 <= remaining <= 100  # Allow small time drift
    
    def test_add_message(self):
        now = datetime.now(timezone.utc)
        window = ContextWindow(
            session_id="sess_123",
            window_start=now,
            window_end=now + timedelta(minutes=5),
            window_number=0,
            messages=[]
        )
        
        msg = ChatMessage(
            role="user",
            content="Hello",
            timestamp=now,
            message_id="msg_1",
            tokens=5
        )
        
        window.add_message(msg)
        assert len(window.messages) == 1
        assert window.messages[0].content == "Hello"
    
    def test_trim_to_token_limit(self):
        """Test that messages are trimmed when exceeding token limit"""
        now = datetime.now(timezone.utc)
        window = ContextWindow(
            session_id="sess_123",
            window_start=now,
            window_end=now + timedelta(minutes=5),
            window_number=0,
            messages=[]
        )
        
        # Add messages that exceed token limit
        for i in range(20):
            msg = ChatMessage(
                role="user",
                content=f"Message {i} " * 100,  # Long message
                timestamp=now,
                message_id=f"msg_{i}",
                tokens=400  # Each message is 400 tokens
            )
            window.add_message(msg)
        
        # Should keep only messages that fit within MAX_CONTEXT_TOKENS
        total_tokens = sum(m.tokens for m in window.messages)
        assert total_tokens <= MAX_CONTEXT_TOKENS
        assert len(window.messages) <= 8  # 3000 / 400 = 7.5


class TestChatMemoryService:
    """Test ChatMemoryService"""
    
    @pytest.fixture
    def mock_redis(self):
        redis_mock = MagicMock()
        redis_mock.ping.return_value = True
        redis_mock.get.return_value = None
        return redis_mock
    
    @pytest.fixture
    def mock_db(self):
        db_mock = MagicMock()
        return db_mock
    
    @pytest.fixture
    def service(self, mock_redis):
        return ChatMemoryService(redis_client=mock_redis, enable_redis=True)
    
    def test_init_with_redis(self, mock_redis):
        service = ChatMemoryService(redis_client=mock_redis)
        assert service.redis is not None
    
    def test_init_without_redis(self):
        service = ChatMemoryService(redis_client=None, enable_redis=False)
        assert service.redis is None
    
    def test_count_tokens(self, service):
        text = "Hello world, this is a test"
        tokens = service.count_tokens(text)
        assert tokens > 0
        assert isinstance(tokens, int)
    
    def test_create_new_window(self, service):
        window = service._create_new_window("sess_123", 0)
        assert window.session_id == "sess_123"
        assert window.window_number == 0
        assert len(window.messages) == 0
        assert not window.is_expired()
    
    def test_get_or_create_context_new_session(self, service, mock_db):
        """Test creating a new session"""
        with patch.object(service, '_get_or_create_from_db') as mock_db_method:
            mock_db_method.return_value = service._create_new_window("sess_123", 0)
            
            context = service.get_or_create_context("sess_123", "user_123", mock_db)
            
            assert context.session_id == "sess_123"
            assert context.window_number == 0
    
    def test_add_interaction(self, service, mock_db):
        """Test adding Q&A to context"""
        session_id = "sess_123"
        
        # Mock the get_or_create to return a fresh window
        with patch.object(service, 'get_or_create_context') as mock_get:
            window = service._create_new_window(session_id, 0)
            mock_get.return_value = window
            
            with patch.object(service, '_save_to_db'):
                context, was_reset = service.add_interaction(
                    session_id=session_id,
                    user_id="user_123",
                    question="What is AI?",
                    response="AI is artificial intelligence",
                    message_id="msg_123",
                    provider="openai",
                    db=mock_db
                )
                
                # Should have 2 messages (Q + A)
                assert len(context.messages) == 2
                assert context.messages[0].role == "user"
                assert context.messages[1].role == "assistant"
                assert not was_reset
    
    def test_context_expiration_triggers_reset(self, service, mock_db):
        """Test that expired context triggers reset"""
        session_id = "sess_123"
        
        # Create an expired window
        now = datetime.now(timezone.utc)
        expired_window = ContextWindow(
            session_id=session_id,
            window_start=now - timedelta(minutes=10),
            window_end=now - timedelta(minutes=5),
            window_number=0,
            messages=[]
        )
        
        with patch.object(service, 'get_or_create_context') as mock_get:
            mock_get.return_value = expired_window
            
            with patch.object(service, '_save_to_db'):
                context, was_reset = service.add_interaction(
                    session_id=session_id,
                    user_id="user_123",
                    question="Hello",
                    response="Hi",
                    message_id="msg_123",
                    provider="openai",
                    db=mock_db
                )
                
                # Should have been reset
                assert was_reset
    
    def test_build_llm_context(self, service):
        """Test building LLM message list"""
        window = service._create_new_window("sess_123", 0)
        
        # Add some messages
        for i in range(3):
            window.add_message(ChatMessage(
                role="user",
                content=f"Question {i}",
                timestamp=datetime.now(timezone.utc),
                message_id=f"msg_{i}",
                tokens=10
            ))
            window.add_message(ChatMessage(
                role="assistant",
                content=f"Answer {i}",
                timestamp=datetime.now(timezone.utc),
                message_id=f"msg_{i}_a",
                tokens=10
            ))
        
        messages = service.build_llm_context(window, "Current question")
        
        # Should have history + current question
        assert len(messages) == 7  # 6 history + 1 current
        assert messages[-1]['role'] == 'user'
        assert messages[-1]['content'] == "Current question"
    
    def test_reset_context(self, service, mock_db):
        """Test manual context reset"""
        with patch.object(service, '_update_session_in_db'):
            context = service.reset_context("sess_123", "user_123", mock_db)
            
            assert context.session_id == "sess_123"
            assert len(context.messages) == 0
            assert not context.is_expired()


class TestRaceConditions:
    """Test thread safety and race conditions"""
    
    @pytest.fixture
    def service(self):
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        return ChatMemoryService(redis_client=mock_redis)
    
    def test_concurrent_message_sending(self, service):
        """Test multiple threads sending messages simultaneously"""
        session_id = "sess_concurrent"
        mock_db = MagicMock()
        
        def send_message(i):
            with patch.object(service, 'get_or_create_context') as mock_get:
                window = service._create_new_window(session_id, 0)
                mock_get.return_value = window
                
                with patch.object(service, '_save_to_db'):
                    context, was_reset = service.add_interaction(
                        session_id=session_id,
                        user_id=f"user_{i}",
                        question=f"Question {i}",
                        response=f"Answer {i}",
                        message_id=f"msg_{i}",
                        provider="openai",
                        db=mock_db
                    )
                    return len(context.messages)
        
        # Simulate 10 concurrent requests
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(send_message, i) for i in range(10)]
            results = [f.result() for f in futures]
        
        # All should complete without errors
        assert len(results) == 10
        assert all(r >= 2 for r in results)  # Each added at least Q+A


class TestFailureScenarios:
    """Test failure handling"""
    
    @pytest.fixture
    def service(self):
        return ChatMemoryService(redis_client=None, enable_redis=False)
    
    def test_redis_failure_fallback(self, service):
        """Test that DB fallback works when Redis fails"""
        mock_db = MagicMock()
        
        # Simulate Redis being unavailable
        service.redis = MagicMock()
        service.redis.get.side_effect = Exception("Redis connection failed")
        
        with patch.object(service, '_get_or_create_from_db') as mock_db_method:
            mock_db_method.return_value = service._create_new_window("sess_123", 0)
            
            # Should not raise exception
            context = service.get_or_create_context("sess_123", "user_123", mock_db)
            
            assert context is not None
            assert mock_db_method.called
    
    def test_db_save_failure_non_fatal(self, service):
        """Test that DB save failure doesn't crash the request"""
        mock_db = MagicMock()
        
        with patch.object(service, 'get_or_create_context') as mock_get:
            window = service._create_new_window("sess_123", 0)
            mock_get.return_value = window
            
            # Simulate DB save failure
            with patch.object(service, '_save_to_db', side_effect=Exception("DB error")):
                # Should not raise exception
                context, was_reset = service.add_interaction(
                    session_id="sess_123",
                    user_id="user_123",
                    question="Hello",
                    response="Hi",
                    message_id="msg_123",
                    provider="openai",
                    db=mock_db
                )
                
                # Context should still be updated in memory
                assert len(context.messages) == 2
    
    def test_token_limit_enforcement(self, service):
        """Test that token limits are enforced"""
        window = service._create_new_window("sess_123", 0)
        
        # Try to add messages exceeding token limit
        huge_message = "x" * 50000  # Huge message
        tokens = service.count_tokens(huge_message)
        
        msg = ChatMessage(
            role="user",
            content=huge_message,
            timestamp=datetime.now(timezone.utc),
            message_id="msg_huge",
            tokens=tokens
        )
        
        window.add_message(msg)
        
        # Total tokens should be capped
        total = sum(m.tokens for m in window.messages)
        assert total <= MAX_CONTEXT_TOKENS


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])