"""
反思模块 (Reflect Module)

Implement Stanford GA's reflection mechanism:
1. monitor accumulated importance, trigger reflection when threshold is reached
2. generate high-level reflection questions
3. retrieve relevant memories
4. generate insights using LLM
5. store insights back into memory stream

References: Stanford Generative Agents paper
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import time
from loguru import logger
from .concept_node import ConceptNode

TAG = __name__


class ReflectModule:
    """
    reflection module - extract high-level insights from experiences
    
    This is the second step of Stanford GA's cognitive loop: Reflect
    """
    
    def __init__(
        self,
        threshold: int = 150,  # accumulated importance threshold
        depth: int = 3,  # number of insights generated per reflection
        min_time_interval: float = 3600,  # minimum reflection interval (seconds), default 1 hour
        enabled: bool = True,  # whether to enable reflection
    ):
        """
        initialize reflection module
        
        Args:
            threshold: accumulated importance threshold, trigger reflection when reached
            depth: number of insights generated per reflection
            min_time_interval: minimum reflection interval (seconds), default 1 hour
            enabled: whether to enable reflection
        """
        self.threshold = threshold
        self.depth = depth
        self.min_time_interval = min_time_interval
        self.enabled = enabled
        
        # reflection state
        # initialize to 0, so that the first reflection is not limited by the time interval
        self.last_reflection_time: float = 0.0
        self.accumulated_importance: int = 0
        
        logger.bind(tag=TAG).info(
            f"ReflectModule initialized: threshold={threshold}, depth={depth}, "
            f"min_interval={min_time_interval}s, enabled={enabled}"
        )
    
    def should_reflect(
        self,
        accumulated_importance: Optional[int] = None,
        current_time: Optional[float] = None
    ) -> bool:
        """
        check if should trigger reflection
        
        Args:
            accumulated_importance: current accumulated importance (optional, if not provided use internal state)
            current_time: current timestamp (optional)
        
        Returns:
            whether to trigger reflection
        """
        if not self.enabled:
            return False
        
        if current_time is None:
            current_time = time.time()
        
        # use provided accumulated importance or internal state
        importance = accumulated_importance if accumulated_importance is not None else self.accumulated_importance
        
        # check 1: accumulated importance threshold reached
        importance_threshold_met = importance >= self.threshold
        
        # check 2: time interval since last reflection exceeded minimum interval
        time_elapsed = current_time - self.last_reflection_time
        time_interval_met = time_elapsed >= self.min_time_interval
        
        should_reflect = importance_threshold_met and time_interval_met
        
        if should_reflect:
            logger.bind(tag=TAG).info(
                f"Reflection triggered: accumulated_importance={importance}, "
                f"threshold={self.threshold}, time_elapsed={time_elapsed:.0f}s"
            )
        
        return should_reflect
    
    def generate_reflection_questions(
        self,
        agent_name: str,
        recent_memories: List[ConceptNode],
        focus_points: Optional[List[str]] = None,
        use_llm: bool = False,
        llm = None
    ) -> List[str]:
        """
        generate reflection questions
        
        According to Stanford GA paper, reflection questions should be high-level, open-ended questions,
        for example: "What is the user interested in recently?", "How is the user's emotion changing?"
        
        Args:
            agent_name: Agent name
            recent_memories: recent memory list
            focus_points: focus points (optional), for example: ["emotion", "interest", "relationship"]
            use_llm: whether to use LLM to generate questions
            llm: LLM instance (required when use_llm=True)
        
        Returns:
            reflection questions list
        """
        if use_llm and llm:
            # use LLM to generate questions (Stanford GA original design)
            return self._generate_questions_with_llm(
                agent_name=agent_name,
                recent_memories=recent_memories,
                llm=llm,
                num_questions=self.depth
            )
        
        # use template to generate questions (fast mode)
        return self._generate_questions_from_template(
            agent_name=agent_name,
            focus_points=focus_points
        )
    
    def _generate_questions_from_template(
        self,
        agent_name: str,
        focus_points: Optional[List[str]] = None
    ) -> List[str]:
        """
        use template to generate reflection questions (fast mode)
        
        Args:
            agent_name: Agent name
            focus_points: focus points list
            
        Returns:
            questions list
        """
        if not focus_points:
            focus_points = ["core focus", "emotion state", "behavior mode"]
        
        questions = []
        
        # generate one question for each focus point
        for focus in focus_points[:self.depth]:
            if focus == "core focus":
                question = f"{agent_name} What are the most important topics or events that {agent_name} is interested in recently?"
            elif focus == "emotion state":
                question = f"{agent_name} How is the user's emotion changing recently?"
            elif focus == "behavior mode":
                question = f"{agent_name} What are the user's recent behavior patterns? What are the user's recent habits or tendencies?"
            elif focus == "relationship":
                question = f"{agent_name} How is the user's relationship with others? What are the user's important social interactions?"
            elif focus == "target":
                question = f"{agent_name} What are the user's recent targets or plans? How is the user's progress?"
            elif focus == "demand":
                question = f"{agent_name} What are the user's current demands or expectations?"
            else:
                question = f"About {focus}, what are the user's recent notable？"
            
            questions.append(question)
        
        logger.bind(tag=TAG).debug(f"Generated {len(questions)} reflection questions (template mode)")
        
        return questions
    
    def _generate_questions_with_llm(
        self,
        agent_name: str,
        recent_memories: List[ConceptNode],
        llm,
        num_questions: int = 3
    ) -> List[str]:
        """
        use LLM to generate reflection questions (Stanford GA original design)
        
        Args:
            agent_name: Agent name
            recent_memories: recent memory list
            llm: LLM instance
            num_questions: number of questions to generate
            
        Returns:
            questions list
        """
        import asyncio
        
        # format recent memories
        memories_text = self._format_memories_for_prompt(recent_memories[:20])
        
        # build prompt (reference Stanford GA original design)
        prompt = f"""
{agent_name} has the following experiences and conversations recently:

{memories_text}

Based on the above content, please generate {num_questions} high-level reflection questions.
These questions should help {agent_name} better understand:
- relationship and social dynamics
- current focus and concerns
- interests and expectations
- emotional patterns and changes

Requirements:
1. The questions should be open-ended, requiring deep thinking
2. The questions should be based on specific memory content, not general discussion
3. Each question should be on a separate line, no numbering

Please generate {num_questions} questions:
"""
        
        try:
            # synchronous call (if in asynchronous context)
            if asyncio.iscoroutinefunction(getattr(llm, 'response_no_stream', None)):
                # needs to run in asynchronous environment
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # in running event loop, use run_coroutine_threadsafe
                    import concurrent.futures
                    future = asyncio.run_coroutine_threadsafe(
                        llm.response_no_stream(
                            system_prompt="You are a helpful AI assistant that is good at asking deep questions. Please only return questions, do not add any other content.",
                            user_prompt=prompt,
                            max_tokens=200
                        ),
                        loop
                    )
                    response = future.result(timeout=30)
                else:
                    response = loop.run_until_complete(
                        llm.response_no_stream(
                            system_prompt="You are a helpful AI assistant that is good at asking deep questions. Please only return questions, do not add any other content.",
                            user_prompt=prompt,
                            max_tokens=200
                        )
                    )
            elif hasattr(llm, 'generate_sync'):
                response = llm.generate_sync(prompt)
            else:
                # downgrade to template mode
                logger.bind(tag=TAG).warning("LLM not compatible for sync call, falling back to template")
                return self._generate_questions_from_template(agent_name)
            
            # parse response
            questions = [q.strip() for q in response.strip().split('\n') if q.strip()]
            
            # filter out too short lines (可能是编号或空行)
            questions = [q for q in questions if len(q) > 10]
            
            # limit number
            questions = questions[:num_questions]
            
            if questions:
                logger.bind(tag=TAG).info(f"Generated {len(questions)} reflection questions (LLM mode)")
                return questions
            else:
                # if LLM did not generate valid questions, fallback to template mode
                logger.bind(tag=TAG).warning("LLM generated no valid questions, falling back to template")
                return self._generate_questions_from_template(agent_name)
                
        except Exception as e:
            logger.bind(tag=TAG).error(f"LLM question generation failed: {e}")
            return self._generate_questions_from_template(agent_name)
    
    async def generate_reflection_questions_async(
        self,
        agent_name: str,
        recent_memories: List[ConceptNode],
        llm,
        num_questions: int = 3
    ) -> List[str]:
        """
        asynchronous version: use LLM to generate reflection questions
        
        Args:
            agent_name: Agent name
            recent_memories: recent memory list
            llm: LLM instance (supports LiteLLMProvider or has response_no_stream method)
            num_questions: number of questions to generate
            
        Returns:
            questions list
        """
        # format recent memories
        memories_text = self._format_memories_for_prompt(recent_memories[:20])
        
        # build prompt
        prompt = f"""
{agent_name} has the following experiences and conversations recently:

{memories_text}

Based on the above content, please generate {num_questions} high-level reflection questions.
These questions should help {agent_name} better understand:
- relationship and social dynamics
- current focus and concerns
- interests and expectations
- emotional patterns and changes

Requirements:
1. The questions should be open-ended, requiring deep thinking
2. The questions should be based on specific memory content, not general discussion
3. Each question should be on a separate line, no numbering

Please generate {num_questions} questions:
"""
        
        try:
            # use unified LLM call method
            response = await self._call_llm(
                llm=llm,
                system_prompt="You are a helpful AI assistant that is good at asking deep questions. Please only return questions, do not add any other content.",
                user_prompt=prompt,
                max_tokens=200
            )
            
            # parse response
            questions = [q.strip() for q in response.strip().split('\n') if q.strip()]
            questions = [q for q in questions if len(q) > 10]
            questions = questions[:num_questions]
            
            if questions:
                logger.bind(tag=TAG).info(f"Generated {len(questions)} reflection questions (async LLM mode)")
                return questions
            else:
                return self._generate_questions_from_template(agent_name)
                
        except Exception as e:
            logger.bind(tag=TAG).error(f"Async LLM question generation failed: {e}")
            return self._generate_questions_from_template(agent_name)
    
    def _format_memories_for_prompt(self, memories: List[ConceptNode]) -> str:
        """
        format memory list for prompt
        
        Args:
            memories: memory list
            
        Returns:
            formatted string
        """
        if not memories:
            return "(no memory)"
        
        formatted = []
        for i, mem in enumerate(memories, 1):
            if hasattr(mem, 'content'):
                content = mem.content
                age_hours = mem.get_age_hours() if hasattr(mem, 'get_age_hours') else 0
                importance = mem.importance if hasattr(mem, 'importance') else 5
                formatted.append(f"- [{age_hours:.1f}小时前, 重要性{importance}] {content}")
            elif isinstance(mem, tuple) and len(mem) >= 2:
                # (ConceptNode, score) 格式
                node, score = mem[0], mem[1]
                content = node.content if hasattr(node, 'content') else str(node)
                age_hours = node.get_age_hours() if hasattr(node, 'get_age_hours') else 0
                importance = node.importance if hasattr(node, 'importance') else 5
                formatted.append(f"- [{age_hours:.1f}小时前, 重要性{importance}] {content}")
            else:
                formatted.append(f"- {str(mem)}")
        
        return "\n".join(formatted)
    
    async def generate_insights(
        self,
        questions: List[str],
        relevant_memories: List[Tuple[ConceptNode, float]],
        llm,
        agent_name: str = "user"
    ) -> List[Dict[str, Any]]:
        """
        generate insights based on questions and relevant memories using LLM
        
        Args:
            questions: reflection questions list
            relevant_memories: relevant memories list (memory node, relevance score)
            llm: LLM instance (supports LiteLLMProvider or has response_no_stream method)
            agent_name: Agent name
        
        Returns:
            insights list, each insight contains:
            - question: question
            - insight: insight content
            - evidence: support evidence (memory ID list)
            - importance: importance score
        """
        insights = []
        
        for question in questions:
            try:
                # build reflection prompt
                prompt = self._build_reflection_prompt(
                    question=question,
                    memories=relevant_memories,
                    agent_name=agent_name
                )
                
                # use LLM to generate insights - supports multiple LLM interfaces
                insight_text = await self._call_llm(
                    llm=llm,
                    system_prompt="You are a helpful AI assistant that is good at observing and summarizing. You can extract deep insights from conversations.",
                    user_prompt=prompt,
                    max_tokens=300
                )
                
                # extract support evidence (memory ID)
                evidence = [node.node_id for node, score in relevant_memories[:5]]
                
                # assess insight importance (reflection generated insights have default higher importance)
                importance = self._assess_insight_importance(insight_text, question)
                
                insight = {
                    "question": question,
                    "insight": insight_text.strip(),
                    "evidence": evidence,
                    "importance": importance
                }
                
                insights.append(insight)
                logger.bind(tag=TAG).debug(f"Generated insight for question: {question[:50]}...")
                
            except Exception as e:
                logger.bind(tag=TAG).error(f"Failed to generate insight for question '{question}': {e}")
        
        logger.bind(tag=TAG).info(f"Generated {len(insights)} insights from {len(questions)} questions")
        
        return insights
    
    async def _call_llm(
        self,
        llm,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 300
    ) -> str:
        """
        call LLM to generate text - supports multiple LLM interfaces
        
        Supports:
        1. LiteLLMProvider (using chat method)
        2. LLM with response_no_stream method
        3. LLM with generate method
        
        Args:
            llm: LLM instance
            system_prompt: system prompt
            user_prompt: user prompt
            max_tokens: maximum token number
        
        Returns:
            generated text
        """
        # use chat method (LiteLLMProvider standard interface)
        if hasattr(llm, 'chat'):
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            response = await llm.chat(
                messages=messages,
                tools=None,
                max_tokens=max_tokens,
                temperature=0.7
            )
            return response.content or ""
        
        # fallback to response_no_stream method
        if hasattr(llm, 'response_no_stream'):
            return await llm.response_no_stream(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens
            )
        
        # fallback to generate method
        if hasattr(llm, 'generate'):
            full_prompt = f"{system_prompt}\n\n{user_prompt}"
            return await llm.generate(full_prompt)
        
        raise RuntimeError(f"LLM instance {type(llm).__name__} has no compatible method (chat, response_no_stream, or generate)")
    
    def _build_reflection_prompt(
        self,
        question: str,
        memories: List[Tuple[ConceptNode, float]],
        agent_name: str
    ) -> str:
        """
        build reflection prompt
        
        Args:
            question: reflection question
            memories: relevant memories list
            agent_name: Agent name
        
        Returns:
            complete prompt
        """
        # format memory list
        memory_texts = []
        for i, (node, score) in enumerate(memories[:20], 1):  # limit to 20 memories
            age_hours = node.get_age_hours()
            memory_texts.append(
                f"{i}. [{age_hours:.1f} hours ago, importance {node.importance}] {node.content}"
            )
        
        memories_section = "\n".join(memory_texts) if memory_texts else "(no relevant memories)"
        
        prompt = f"""
Based on the following memories of {agent_name}, please answer this question:

Question: {question} 

Relevant memories:
{memories_section}

Please synthesize the above memories and give a deep insight (2-3 sentences).
Insights should:
1. summarize key patterns or trends
2. based on specific memories, not general discussion
3. help understand {agent_name}

Insights:
"""
        
        return prompt
    
    def _assess_insight_importance(self, insight: str, question: str) -> int:
        """
        assess insight importance
        
        Args:
            insight: insight content
            question: original question
        
        Returns:
            importance score (1-10)
        """
        # reflection generated insights have default higher importance (7-9)
        
        base_importance = 7
        
        # high importance keywords
        high_importance_keywords = [
            "重要", "关键", "核心", "主要", "显著",
            "明显", "强烈", "深刻", "持续", "频繁",
            "important", "key", "core", "main", "significant",
            "obvious", "strong", "deep", "continuous", "frequent",
        ]
        
        # medium importance keywords
        medium_importance_keywords = [
            "倾向", "趋势", "可能", "似乎", "表现出",
            "tendency", "trend", "possible", "seems", "show",
        ]
        
        # check keywords
        insight_lower = insight.lower()
        
        if any(kw in insight_lower for kw in high_importance_keywords):
            return min(9, base_importance + 2)
        elif any(kw in insight_lower for kw in medium_importance_keywords):
            return min(8, base_importance + 1)
        else:
            return base_importance
    
    def update_reflection_state(
        self,
        current_time: Optional[float] = None,
        reset_accumulation: bool = True
    ):
        """
        update reflection state (call after one reflection)
        
        Args:
            current_time: current timestamp
            reset_accumulation: whether to reset accumulated importance
        """
        if current_time is None:
            current_time = time.time()
        
        self.last_reflection_time = current_time
        
        if reset_accumulation:
            self.accumulated_importance = 0
        
        logger.bind(tag=TAG).debug(
            f"Reflection state updated: last_time={current_time}, "
            f"accumulated_importance={'reset to 0' if reset_accumulation else self.accumulated_importance}"
        )
    
    def add_importance(self, importance: int):
        """
        add to accumulated importance
        
        Args:
            importance: importance value to add
        """
        self.accumulated_importance += importance


# keep backward compatibility alias
ReflectionEngine = ReflectModule
