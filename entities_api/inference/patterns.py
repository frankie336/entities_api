import json

from entities_api.inference.base_inference import BaseInference
from entities_api.inference.cloud_together_ai_v3 import TogetherV3Inference

json_string = {"name": "vector_store_search", "arguments": {"query": "plans with dogs", "search_type": "temporal", "source_type": "chat", "filters": {"created_at": {"gte": 1709078400, "lte": 1709164800}}}}

service = TogetherV3Inference()
#test = service.parse_nested_function_call_json(text=json_string)
#print(test)


#test = service.is_valid_function_call_response(json_data=json_string)
#print(test)




print(service.is_complex_vector_search(data=json_string))