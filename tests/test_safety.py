import unittest
import json
from nanobot.agent.safety import LoopDetector, LoopDetectedError

class TestLoopDetector(unittest.TestCase):
    def test_loop_detector_text_repeat(self):
        detector = LoopDetector(max_repeats=3)
        
        # Not a loop yet
        detector.add_interaction("Hello", None)
        detector.add_interaction("Hello", None)
        
        # Third time is a loop
        with self.assertRaises(LoopDetectedError):
            detector.add_interaction("Hello", None)

    def test_loop_detector_tool_repeat(self):
        detector = LoopDetector(max_repeats=3)
        
        tool_call = [{"function": {"name": "read_file", "arguments": {"path": "foo.txt"}}}]
        
        detector.add_interaction("Thinking...", tool_call)
        detector.add_interaction("Thinking...", tool_call)
        
        with self.assertRaises(LoopDetectedError):
            detector.add_interaction("Thinking...", tool_call)

    def test_loop_detector_no_loop_alternating(self):
        detector = LoopDetector(max_repeats=3)
        
        tool_call_1 = [{"function": {"name": "read_file", "arguments": {"path": "foo.txt"}}}]
        tool_call_2 = [{"function": {"name": "read_file", "arguments": {"path": "bar.txt"}}}]
        
        # A, B, A, B, A - no consecutive repeat of 3
        detector.add_interaction("Thinking...", tool_call_1)
        detector.add_interaction("Thinking...", tool_call_2)
        detector.add_interaction("Thinking...", tool_call_1)
        detector.add_interaction("Thinking...", tool_call_2)
        detector.add_interaction("Thinking...", tool_call_1)
        
        # No error should be raised
        self.assertTrue(True)

    def test_loop_detector_tool_args_order_insensitive(self):
        """Test that arguments hash is consistent even if dict keys order varies (if passing raw dicts)."""
        detector = LoopDetector(max_repeats=3)
        
        # Args as dicts
        tool_call_1 = [{"function": {"name": "func", "arguments": {"a": 1, "b": 2}}}]
        tool_call_2 = [{"function": {"name": "func", "arguments": {"b": 2, "a": 1}}}]
        
        detector.add_interaction(None, tool_call_1)
        detector.add_interaction(None, tool_call_2)
        
        with self.assertRaises(LoopDetectedError):
            detector.add_interaction(None, tool_call_1)

if __name__ == '__main__':
    unittest.main()
