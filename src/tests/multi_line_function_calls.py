import re
import json
import unittest


# Dummy logging utility for testing purposes.
class DummyLogger:
    @staticmethod
    def debug(msg, *args):
        pass


logging_utility = DummyLogger()


# Dummy class with the extract_tool_invocations method.
class ToolInvocationExtractor:
    def extract_tool_invocations(self, text: str):
        """
        Extracts and validates all tool invocation patterns from unstructured text.
        Handles multi-line JSON and schema validation without recursive patterns.
        """
        # Remove markdown code fences (e.g., ```json ... ```)
        text = re.sub(r"```(?:json)?(.*?)```", r"\1", text, flags=re.DOTALL)

        # Normalization phase
        text = re.sub(r"[“”]", '"', text)
        text = re.sub(r"(\s|\\n)+", " ", text)

        # Simplified pattern without recursion
        pattern = r"""
            \{         # Opening curly brace
            .*?        # Any characters
            "name"\s*:\s*"(?P<name>[^"]+)" 
            .*?        # Any characters
            "arguments"\s*:\s*\{(?P<args>.*?)\}
            .*?        # Any characters
            \}         # Closing curly brace
        """

        tool_matches = []
        for match in re.finditer(pattern, text, re.DOTALL | re.VERBOSE):
            try:
                # Reconstruct with proper JSON formatting
                raw_json = match.group()
                parsed = json.loads(raw_json)

                # Schema validation
                if not all(key in parsed for key in ["name", "arguments"]):
                    continue
                if not isinstance(parsed["arguments"], dict):
                    continue

                tool_matches.append(parsed)
            except (json.JSONDecodeError, KeyError):
                continue

        return tool_matches


class TestExtractToolInvocations(unittest.TestCase):
    def setUp(self):
        self.extractor = ToolInvocationExtractor()

    def test_no_tool_invocation(self):
        # Test input with no JSON tool invocations.
        text = "This is some random text without any JSON objects."
        result = self.extractor.extract_tool_invocations(text)
        self.assertEqual(result, [])

    def test_single_tool_invocation_plain(self):
        # Test with a simple valid JSON tool invocation.
        text = '{"name": "toolA", "arguments": {"param": "value"}}'
        result = self.extractor.extract_tool_invocations(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "toolA")
        self.assertEqual(result[0]["arguments"], {"param": "value"})

    def test_tool_invocation_in_markdown(self):
        # Test with a tool invocation inside markdown code fences.
        text = 'Some text before. ```json {"name": "toolB", "arguments": {"foo": "bar"}} ``` Some text after.'
        result = self.extractor.extract_tool_invocations(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "toolB")
        self.assertEqual(result[0]["arguments"], {"foo": "bar"})

    def test_multiple_tool_invocations(self):
        # Test input with multiple valid JSON tool invocations.
        text = """
            Some random text.
            {"name": "toolC", "arguments": {"a": 1}}Some random text.
            Some random text.
            Some random text.{"name": "toolD", "arguments": {"b": 2}}
        """
        result = self.extractor.extract_tool_invocations(text)
        self.assertEqual(len(result), 2)
        names = {item["name"] for item in result}
        self.assertIn("toolC", names)
        self.assertIn("toolD", names)

    def test_malformed_json(self):
        # Test that a malformed JSON block is skipped.
        text = '{"name": "toolE", "arguments": {"c": 3},}'  # Trailing comma makes it invalid.
        result = self.extractor.extract_tool_invocations(text)
        # Expecting no valid extraction due to invalid JSON.
        self.assertEqual(result, [])

    def test_missing_keys(self):
        # Test input where the JSON object is missing required keys.
        text = '{"name": "toolF"}'
        result = self.extractor.extract_tool_invocations(text)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
