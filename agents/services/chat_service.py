"""
Chat Service

Orchestrates the chat session, AI client interaction, and tool execution.
Refactored from backend/chat/views.py
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction

from chat.models import ChatSession, ChatMessage
from ..clients import get_ai_client
from ..tools.definitions import get_tools
from .tool_executor import ToolExecutor

logger = logging.getLogger('django')


class ChatService:
    """
    Service for handling chat sessions, AI interaction, and persistence.
    """
    
    def __init__(self, user, session_id: Optional[int] = None, project_id: Optional[int] = None, 
                 model_group: Optional[str] = None, model_name: Optional[str] = None):
        self.user = user
        self.session_id = session_id
        self.project_id = project_id
        self.model_group = model_group
        self.model_name = model_name
        self.session = None
        self.client = None
        
    def process_message(self, user_content: Optional[str] = None, messages_payload: Optional[List] = None) -> Dict[str, Any]:
        """
        Process a user message or continuation of a conversation (non-streaming version).
        
        Args:
            user_content: The text content from the user (if any)
            messages_payload: Optional list of messages for context/history (legacy support)
            
        Returns:
            Dictionary with result content and session info.
        """
        # Collect all streamed messages
        new_messages = []
        result = {}
        
        for event in self.process_message_stream(user_content, messages_payload):
            if event.get('type') == 'message':
                new_messages.append({
                    'role': event.get('role'),
                    'content': event.get('content')
                })
            elif event.get('type') == 'done':
                result = {
                    'result': new_messages[-1]['content'] if new_messages else '',
                    'new_messages': new_messages,
                    'session_id': event.get('session_id'),
                    'session_title': event.get('session_title')
                }
        
        return result
    
    def process_message_stream(self, user_content: Optional[str] = None, messages_payload: Optional[List] = None):
        """
        Process a user message with streaming - yields each AI response as it's generated.
        
        Args:
            user_content: The text content from the user (if any)
            messages_payload: Optional list of messages for context/history (legacy support)
            
        Yields:
            Dict events: {"type": "message", "role": "...", "content": "..."} or
                        {"type": "done", "session_id": ..., "session_title": ...}
        """
        # 1. Resolve Session
        self.session = self._resolve_session(user_content)
        
        # 2. Persist User Message
        if user_content:
            ChatMessage.objects.create(
                session=self.session,
                role='user',
                content=user_content
            )
            
        # 3. Initialize Client
        # We need project_id and model_group from session if not provided in init
        pid = self.project_id or self.session.project_id
        group = self.model_group or self.session.model_group
        
        if not pid or not group:
            raise ValueError("Project ID and Model Group are required for AI Client initialization")
            
        self.client = get_ai_client(pid, group)
        
        # 4. Prepare Context
        context_messages = self._build_context()
        
        # 5. Prepare Tools
        tools = get_tools()
        tool_executor = ToolExecutor(project_id=pid, user=self.user)
        
        # 6. Multi-turn Loop
        MAX_ITERATIONS = 10
        iteration = 0
        final_content = ""
        
        # Determine model to use
        request_model = self.model_name or self.session.model
        if not request_model:
            raise ValueError("Model name not specified")

        while iteration < MAX_ITERATIONS:
            # Call AI
            response = self.client.chat_completion(
                messages=context_messages,
                model=request_model,
                tools=tools,
                tool_choice="auto"
            )
            
            content = response.get('content')
            tool_calls = response.get('tool_calls')
            
            # Persist intermediate AI responses if they have content
            if tool_calls:
                # Append to context
                assistant_msg = {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls
                }
                context_messages.append(assistant_msg)
                
                if not content:
                    # Persist marker for tool calls
                    call_descs = []
                    for tc in tool_calls:
                        fname = tc.function.name if hasattr(tc, 'function') else tc.get('function', {}).get('name')
                        call_descs.append(fname)
                        
                    ChatMessage.objects.create(
                        session=self.session,
                        role='tool',
                        content=f"[Requesting Tools: {', '.join(call_descs)}]"
                    )
                else:
                    msg = ChatMessage.objects.create(
                        session=self.session,
                        role='assistant',
                        content=content
                    )
                    # Yield the intermediate message immediately
                    yield {'type': 'message', 'role': 'assistant', 'content': content}
                
                # Execute tools
                tool_results = tool_executor.execute_calls(tool_calls)
                
                # Append results to context
                context_messages.extend(tool_results)
                
                # Persist results
                for res in tool_results:
                    ChatMessage.objects.create(
                        session=self.session,
                        role='tool',
                        content=f"[Tool Result for {res['name']}]: {res['content']}"
                    )
                
                iteration += 1
                continue
            
            # No tool calls, we have final answer
            final_content = content
            break
            
        # 7. Persist Final Answer
        if final_content:
            ChatMessage.objects.create(
                session=self.session,
                role='assistant',
                content=final_content
            )
            # Yield the final message
            yield {'type': 'message', 'role': 'assistant', 'content': final_content}
            
        self.session.save() # Update timestamp
        
        # 8. Check Summary
        self._check_and_summarize(request_model)
        
        # 9. Signal completion
        yield {
            'type': 'done',
            'session_id': self.session.id,
            'session_title': self.session.title
        }

    def _resolve_session(self, user_content: Optional[str]) -> ChatSession:
        """Find or create a chat session."""
        session = None
        if self.session_id:
            try:
                session = ChatSession.objects.get(id=self.session_id, user=self.user)
                # Update settings
                if self.project_id: session.project_id = self.project_id
                if self.model_group: session.model_group = self.model_group
                if self.model_name: session.model = self.model_name
                session.save()
            except ChatSession.DoesNotExist:
                raise ValueError("Session not found")
        else:
            session = ChatSession.objects.create(
                user=self.user,
                project_id=self.project_id,
                model_group=self.model_group,
                model=self.model_name,
                title=user_content[:30] if user_content else "New Chat"
            )
        return session

    def _build_context(self) -> List[Dict[str, Any]]:
        """Build context messages from session history."""
        MAX_CONTEXT = 20
        all_db_messages = self.session.messages.all().order_by('created_at')
        
        if all_db_messages.count() > MAX_CONTEXT:
            recent_messages = all_db_messages[all_db_messages.count() - MAX_CONTEXT :]
        else:
            recent_messages = all_db_messages
            
        context_messages = []
        
        if self.session.summary:
            context_messages.append({
                "role": "system", 
                "content": f"Previous conversation summary: {self.session.summary}"
            })
            
        for m in recent_messages:
            role = m.role
            content = m.content
            
            if role == 'tool':
                role = 'system' # Or 'model'/'assistant' depending on preference, system is safe.
                content = f"Tool Output: {content}"
            
            context_messages.append({"role": role, "content": content})
            
        return context_messages

    def _check_and_summarize(self, model_name: str):
        """Check if we need to summarize history."""
        MAX_HISTORY = 20
        all_messages = self.session.messages.order_by('created_at')
        count = all_messages.count()
        
        if count <= MAX_HISTORY:
            return
            
        message_to_keep = all_messages[count - MAX_HISTORY]
        cutoff_date = message_to_keep.created_at
        
        candidates = self.session.messages.filter(created_at__lt=cutoff_date).order_by('created_at')
        if self.session.last_summarized_message_id:
             candidates = candidates.filter(id__gt=self.session.last_summarized_message_id)
             
        if not candidates.exists():
            return
            
        logger.info(f"Summarizing {candidates.count()} messages for session {self.session.id}")
        
        text_lines = [f"{m.role}: {m.content}" for m in candidates]
        conversation_text = "\n".join(text_lines)
        
        old_summary = self.session.summary or "None"
        prompt = f"""
        Current summary of conversation: {old_summary}
        
        New lines to add to summary:
        {conversation_text}
        
        Update the summary to include the new information concisely. 
        Keep it brief and focused on key facts and user preferences.
        """
        
        try:
            new_summary = self.client.generate_text(prompt, model=model_name)
            
            self.session.summary = new_summary
            self.session.last_summarized_message_id = candidates.last().id
            self.session.save()
            
        except Exception as e:
            logger.error(f"Failed to summarize session {self.session.id}: {e}")
