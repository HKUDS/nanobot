"""
ImportanceScorer - importance scoring

Evaluates the importance of memory (1-10 points)
Can use rules or LLM for evaluation
"""

from typing import Optional
import re
from loguru import logger

TAG = __name__



class ImportanceScorer:
    """importance scoring"""
    
    def __init__(self, use_llm: bool = False):
        """
        initialize importance scoring
        
        Args:
            use_llm: whether to use LLM for scoring (more accurate but costly)
        """
        self.use_llm = use_llm
        
        # keyword weights (based on rules)
        self.keyword_weights = {
            # emotional related (high importance)
            '爱': 9, '恨': 9, '死': 9, '生': 8,
            '失恋': 9, '结婚': 9, '分手': 8, '离婚': 9,
            '开心': 7, '难过': 7, '高兴': 7, '伤心': 8,
            '焦虑': 7, '害怕': 7, '恐惧': 8, '担心': 6,
            '感动': 7, '激动': 7, '兴奋': 7,
            
            'love': 9, 'hate': 9, 'death': 9, 'birth': 8,
            'breakup': 9, 'marriage': 9, 'divorce': 8,
            'happy': 7, 'sad': 7, 'excited': 7, 'depressed': 8,
            'anxious': 7, 'afraid': 7, 'fearful': 8, 'worried': 6,
            'touched': 7, 'excited': 7, 'excited': 7,
            
            # important events (high importance)
            '工作': 7, '换工作': 8, '辞职': 8, '失业': 8,
            '家人': 8, '父母': 8, '孩子': 8, '朋友': 6,
            '生病': 8, '住院': 9, '手术': 9,
            '搬家': 7, '买房': 8, '买车': 7,

            'work': 7, 'change job': 8, 'quit job': 8, 'unemployed': 8,
            'family': 8, 'parents': 8, 'children': 8, 'friends': 6,
            'sick': 8, 'hospital': 9, 'operation': 9,
            'move': 7, 'buy house': 8, 'buy car': 7,
            
            # daily (medium importance)
            '吃饭': 3, '睡觉': 3, '天气': 2,
            '电影': 4, '游戏': 4, '运动': 5,
            '学习': 6, '考试': 7, '毕业': 8,
            
            'eat': 3, 'sleep': 3, 'weather': 2,
            'movie': 4, 'game': 4, 'sport': 5,
            'study': 6, 'exam': 7, 'graduate': 8,

            # low importance
            '早安': 2, '晚安': 2, '你好': 1,
            '谢谢': 3, '不客气': 2,

            'good morning': 2, 'good night': 2, 'hello': 1,
            'thank you': 3, 'you are welcome': 2,
        }
        
        # special patterns (regular expressions)
        self.special_patterns = [
            (r'我.{0,5}(想|要|打算|计划)', 6),  # intention expression
            (r'(为什么|怎么|如何)', 5),  # question asking
            (r'(应该|必须|一定要)', 6),  # strong attitude
            (r'(从来|永远|总是|一直)', 7),  # absolute expression
            (r'第一次', 8),  # first experience
            (r'(重要|关键|紧急)', 8),  # explicit importance

            (fr'Im.{0,5}(thinking|thinking about|thinking of|thinking of doing|thinking of doing something|thinking of doing something else)', 6),  # thinking expression
            (fr'I.{0,5}(want|want to|want to do|want to do something|want to do something else)', 6),  # want expression
            (fr'I.{0,5}(plan|planning|planning to|planning to do|planning to do something|planning to do something else)', 6),  # plan expression
            (fr'I.{0,5}(decide|deciding|decided|decided to|decided to do|decided to do something|decided to do something else)', 6),  # decide expression
            (fr'I.{0,5}(decide|deciding|decided|decided to|decided to do|decided to do something|decided to do something else)', 6),  # decide expression
        ]
    
    def score(self, content: str, role: str = "user", llm = None) -> int:
        """
        evaluate memory importance
        
        Args:
            content: memory content
            role: role (user/assistant)
            llm: LLM instance (if use_llm=True)
        
        Returns:
            importance score (1-10)
        """
        # if LLM is enabled and an LLM instance is provided
        if self.use_llm and llm:
            return self._score_with_llm(content, llm)
        else:
            return self._score_with_rules(content, role)
    
    def _score_with_rules(self, content: str, role: str) -> int:
        """score with rules"""
        
        # base score
        base_score = 5
        
        #  lower importance
        if role == "assistant":
            base_score = 4
        
        # check keywords
        max_keyword_score = 0
        for keyword, weight in self.keyword_weights.items():
            if keyword in content:
                max_keyword_score = max(max_keyword_score, weight)
        
        # check special patterns
        max_pattern_score = 0
        for pattern, weight in self.special_patterns:
            if re.search(pattern, content):
                max_pattern_score = max(max_pattern_score, weight)
        
        # comprehensive scoring (take the maximum value)
        final_score = max(base_score, max_keyword_score, max_pattern_score)
        
        # content length affects (short content reduces importance)
        if len(content) < 5:
            final_score = min(final_score, 3)
        elif len(content) < 10:
            final_score = min(final_score, 5)
        
        # ensure within 1-10 range
        final_score = max(1, min(10, final_score))
        
        logger.bind(tag=TAG).debug(
            f"rules scoring: {content[:30]}... -> {final_score}"
        )
        
        return final_score
    
    def _score_with_llm(self, content: str, llm) -> int:
        """score with LLM (more accurate but costly)"""
        try:
            prompt = f"""
Evaluate the importance of the following memory (1-10 points):

Memory content: {content}

Scoring criteria:
- 1-3 points: daily (weather, greetings, etc.)
- 4-6 points: ordinary conversation (interests, daily activities)
- 7-8 points: important events (work, study, relationships)
- 9-10 points: (major events) (death, love, life)

Only return a number (1-10).
"""   
            # call LLM
            response = llm.response_no_stream(
                system_prompt="You are a memory importance evaluation expert.",
                user_prompt=prompt,
                max_tokens=10,
                temperature=0.3
            )
            
            # extract number
            import re
            match = re.search(r'\d+', response)
            if match:
                score = int(match.group())
                score = max(1, min(10, score))  # ensure within 1-10 range
                logger.bind(tag=TAG).debug(f"LLM scoring: {content[:30]}... -> {score}")
                return score
            else:
                logger.bind(tag=TAG).warning(f"LLM scoring failed, using default value: {response}")
                return 5
        
        except Exception as e:
            logger.bind(tag=TAG).error(f"LLM scoring error: {e}")
            # fallback to rules scoring
            return self._score_with_rules(content, "user")
    
    def score_conversation_turn(self, user_msg: str, assistant_msg: str, llm = None) -> tuple:
        """
        evaluate the importance of a conversation turn
        
        Args:
            user_msg: user message
            assistant_msg: assistant message
            llm: LLM instance (optional)
        
        Returns:
            (user message importance, assistant message importance)
        """
        user_importance = self.score(user_msg, "user", llm)
        assistant_importance = self.score(assistant_msg, "assistant", llm)
        
        return user_importance, assistant_importance
