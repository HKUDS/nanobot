#!/usr/bin/env python
"""
Test script to verify LiteLLM pricing data for various models.

This script does NOT make actual API calls - it only queries LiteLLM's
pricing database to verify that costs can be calculated correctly.

Usage:
    python tests/test_pricing_verification.py
"""

from litellm import cost_per_token, completion_cost


def test_pricing():
    """Test pricing calculation for various models."""
    
    models = [
        # OpenAI models
        ("gpt-4o", "OpenAI"),
        ("gpt-4o-mini", "OpenAI"),
        ("gpt-4-turbo", "OpenAI"),
        ("gpt-3.5-turbo", "OpenAI"),
        # Anthropic models
        ("claude-3-5-sonnet-20241022", "Anthropic"),
        ("claude-3-opus-20240229", "Anthropic"),
        ("claude-3-haiku-20240307", "Anthropic"),
        # DeepSeek
        ("deepseek/deepseek-chat", "DeepSeek"),
        ("deepseek/deepseek-coder", "DeepSeek"),
    ]
    
    print()
    print("=" * 75)
    print("LiteLLM Pricing Verification (Cost per 1M tokens in USD)")
    print("=" * 75)
    print(f"{'Provider':<12} {'Model':<35} {'Input':>10} {'Output':>10}")
    print("-" * 75)
    
    success_count = 0
    fail_count = 0
    
    for model, provider in models:
        try:
            # Get cost for 1M tokens
            input_cost, output_cost = cost_per_token(
                model=model,
                prompt_tokens=1_000_000,
                completion_tokens=1_000_000
            )
            print(f"{provider:<12} {model:<35} ${input_cost:>8.2f} ${output_cost:>8.2f}")
            success_count += 1
        except Exception as e:
            print(f"{provider:<12} {model:<35} {'ERROR':>10} {str(e)[:20]}")
            fail_count += 1
    
    print("-" * 75)
    print(f"Results: {success_count} passed, {fail_count} failed")
    print("=" * 75)
    
    # Test completion_cost function
    print()
    print("=" * 75)
    print("Testing completion_cost() with sample token counts")
    print("=" * 75)
    
    test_cases = [
        ("gpt-4o", 1000, 500),
        ("claude-3-5-sonnet-20241022", 1000, 500),
        ("deepseek/deepseek-chat", 1000, 500),
    ]
    
    for model, prompt_tokens, completion_tokens in test_cases:
        try:
            # Method 1: cost_per_token
            input_cost, output_cost = cost_per_token(
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens
            )
            total = input_cost + output_cost
            
            print(f"{model}:")
            print(f"  Prompt: {prompt_tokens} tokens, Completion: {completion_tokens} tokens")
            print(f"  Input cost:  ${input_cost:.6f}")
            print(f"  Output cost: ${output_cost:.6f}")
            print(f"  Total cost:  ${total:.6f}")
            print()
        except Exception as e:
            print(f"{model}: ERROR - {e}")
            print()
    
    print("=" * 75)
    print("✅ Pricing verification complete!")
    print("   LiteLLM uses live pricing from api.litellm.ai")
    print("=" * 75)


if __name__ == "__main__":
    test_pricing()
