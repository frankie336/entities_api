# test_inference_factory.py
import unittest
from unittest.mock import patch
from entities_api.inference.llama_local import LlamaLocal
from entities_api.inference.groq_inference import CloudInference
# test_inference_factory.py

from entities_api.inference.inference_factory import InferenceFactory


# Add other necessary imports

class TestInferenceFactory(unittest.TestCase):
    @patch('inference_factory.DeepSeekR1Local')
    def test_get_local_inference(self, mock_local_inference):
        inference = InferenceFactory.get_inference('local')
        mock_local_inference.assert_called_once()
        self.assertIsInstance(inference, LlamaLocal)

    @patch('inference_factory.CloudInference')
    def test_get_cloud_inference(self, mock_cloud_inference):
        inference = InferenceFactory.get_inference('cloud')
        mock_cloud_inference.assert_called_once()
        self.assertIsInstance(inference, CloudInference)

    def test_get_unknown_inference(self):
        with self.assertRaises(ValueError):
            InferenceFactory.get_inference('unknown')

if __name__ == '__main__':
    unittest.main()
