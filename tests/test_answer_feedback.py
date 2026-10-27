import unittest

from app.services.answer_feedback import build_answer_feedback_prompt,generate_answer_feedback
from types import SimpleNamespace
from unittest.mock import patch


class AnswerFeedbackPromptTest(unittest.TestCase):
    def test_prompt_contains_answer_context(self):
        prompt = build_answer_feedback_prompt(
            question="依赖注入的主要作用是什么？",
            options={"A": "降低耦合", "B": "增加耦合", "C": None, "D": None},
            user_answer="B",
            correct_answer="A",
            explanation="依赖注入让组件依赖抽象而不是具体实现。",
        )

        self.assertIn("依赖注入的主要作用是什么？", prompt)
        self.assertIn('"user_answer": "B"', prompt)
        self.assertIn('"correct_answer": "A"', prompt)
        self.assertIn('"is_correct": false', prompt)
        self.assertIn("降低耦合", prompt)

class AnswerFeedbackGenerationTest(unittest.TestCase):
    @patch("app.services.answer_feedback.deepseek_client")
    def test_returns_stripped_provider_feedback(self, client_factory):
        provider = client_factory.return_value.chat.completions.create
        provider.return_value = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="  你已找到了关键概念，继续巩固。  ")
            )]
        )

        feedback = generate_answer_feedback(
            question="依赖注入的主要作用是什么？",
            options={"A": "降低耦合", "B": "增加耦合", "C": None, "D": None},
            user_answer="A",
            correct_answer="A",
            explanation="依赖注入让组件依赖抽象而不是具体实现。",
        )

        self.assertEqual(feedback, "你已找到了关键概念，继续巩固。")
        client_factory.assert_called_once_with("feedback")
        self.assertEqual(provider.call_args.kwargs["model"], "deepseek-chat")
