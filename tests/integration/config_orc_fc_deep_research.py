import dotenv

dotenv.load_dotenv()


# hyperbolic/meta-llama/Llama-3.3-70B-Instruct
# hyperbolic/deepseek-ai/DeepSeek-V3
# hyperbolic/Qwen/Qwen3-235B-A22B
# hyperbolic/Qwen/Qwen2.5-VL-7B-Instruct
# hyperbolic/openai/gpt-oss-120b
# together-ai/deepcogito/cogito-v2-1-671b
# together-ai/ServiceNow-AI/Apriel-1.6-15b-Thinker


# together-ai/deepcogito/cogito-v2-preview-llama-109B-MoE <-- Model not available
# together-ai/deepcogito/cogito-v2-preview-llama-405B <-- model not available
# together-ai/deepcogito/cogito-v2-preview-llama-70B < -- model not available

# together-ai/deepseek-ai/DeepSeek-R1-0528-tput < -- model not available
# together-ai/deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free < -- model not available

# together-ai/google/gemma-2b-it-Ishan <---Input validation error: `inputs` tokens + `max_new_tokens` must be <= 8193

# together-ai/meta-llama/Llama-3-70b-hf < -- Not entities appropved list
# together-ai/meta-llama/Llama-3.1-405B-Instruct < -- Not in approved list
# together-ai/meta-llama/Llama-3.2-1B-Instruct < -- Not in approved list

DEEP_RESEARCH_TEST_SUITE = {
    "test_1_deep_comparative": {
        "name": "Deep Comparative (Multi-Metric)",
        "query": (
            "Compare NVIDIA and AMD's 2024 performance across:\n"
            "1. Annual revenue\n"
            "2. Data center segment revenue\n"
            "3. Gaming segment revenue\n"
            "4. Year-over-year growth rates\n\n"
            "Cite official investor relations sources."
        ),
        "expected_sources": 4,  # 2 per company minimum
        "complexity": "TIER_2",
        "validates": ["multi_entity_research", "segment_breakdown", "source_citation"],
    },
    "test_2_trend_analysis": {
        "name": "Trend Analysis (Temporal Depth)",
        "query": (
            "How has NVIDIA's data center revenue grown from 2021 to 2024? "
            "Include quarterly breakdowns for 2024 and identify key inflection points."
        ),
        "expected_sources": 5,  # Multiple years + quarterly data
        "complexity": "TIER_3",
        "validates": [
            "temporal_research",
            "quarterly_granularity",
            "trend_identification",
        ],
    },
    "test_3_multi_source_verification": {
        "name": "Multi-Source Verification",
        "query": (
            "What was SpaceX's valuation in its most recent funding round? "
            "Verify the answer from at least 3 different sources and note any discrepancies."
        ),
        "expected_sources": 3,  # Explicitly required
        "complexity": "TIER_2",
        "validates": ["source_diversity", "conflict_detection", "verification_depth"],
    },
    "test_4_complex_synthesis": {
        "name": "Complex Synthesis (Multi-Vendor)",
        "query": (
            "What are the key differences between AWS, Azure, and Google Cloud's "
            "AI infrastructure offerings as of Q4 2024? Focus on:\n"
            "- GPU availability (H100, A100)\n"
            "- Pricing per compute hour\n"
            "- Integration with major ML frameworks"
        ),
        "expected_sources": 6,  # 2 per cloud provider
        "complexity": "TIER_3",
        "validates": [
            "multi_entity_research",
            "technical_comparison",
            "synthesis_quality",
        ],
    },
    "test_5_edge_case": {
        "name": "Edge Case (Requires Scrolling/Search)",
        "query": (
            "Find the exact date and location of Anthropic's Series C funding announcement. "
            "Include the lead investors and round size."
        ),
        "expected_sources": 2,
        "complexity": "TIER_1",
        "validates": [
            "specific_fact_retrieval",
            "search_web_page_usage",
            "detail_accuracy",
        ],
    },
    # BONUS: The original failing test for regression checking
    "test_0_baseline": {
        "name": "Baseline (Original Bug Test)",
        "query": (
            "Find the 2024 revenue of NVIDIA and compare it to AMD's 2024 revenue. "
            "Save your findings to the scratchpad before answering."
        ),
        "expected_sources": 2,  # 1 per company minimum
        "complexity": "TIER_1",
        "validates": [
            "both_entities_researched",
            "scratchpad_usage",
            "basic_comparison",
        ],
    },
}


PROMPTS = {
    "RESEARCH": (
        "Find the 2024 revenue of NVIDIA and compare it to AMD's 2024 revenue. "
        "Save your findings to the scratchpad before answering."
    ),
    "EXTERNAL": ("Check the flight times from LAX to JFK."),
}

config = {
    "together_api_key": "",
    "entities_api_key": "",
    "entities_user_id": "",
    "base_url": "http://localhost:9000",
    "url": "https://api.together.xyz/v1/chat/completions",
    "model": "together-ai/Qwen/Qwen3-Next-80B-A3B-Instruct",
    "provider": "together",
    "assistant_id": "asst_13HyDgBnZxVwh5XexYu74F",
    "test_prompt": DEEP_RESEARCH_TEST_SUITE["test_0_baseline"][
        "query"
    ],  # The baseline/original test
    # or
    # "test_prompt": DEEP_RESEARCH_TEST_SUITE["test_1_deep_comparative"]["query"],
    # or
    # "test_prompt": DEEP_RESEARCH_TEST_SUITE["test_3_multi_source_verification"]["query"],
}
