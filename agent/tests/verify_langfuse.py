import sys
import os

# Add the project root and agent directory to sys.path to allow imports
current_dir = os.path.dirname(os.path.abspath(__file__))
agent_dir = os.path.dirname(current_dir)
project_root = os.path.dirname(agent_dir)
sys.path.extend([project_root, agent_dir])

from integrations.langfuse_client import trace_llm_call, get_trace_url

def verify_langfuse():
    """
    Verification script for Langfuse integration.
    """
    print("🚀 Starting Langfuse verification...")
    
    test_input = {"test": "langfuse connection verification"}
    test_name = "test-setup"
    test_model = "test-model"
    
    with trace_llm_call(
        name=test_name,
        input_data=test_input,
        model=test_model,
        metadata={"env": "verification"}
    ) as trace_id:
        print(f"✅ Created test trace: {trace_id}")
        
        # Simulate an output
        test_output = {"result": "connection successful"}
        
        # Record details to the handle
        trace_id.output = test_output
        trace_id.token_counts = {"prompt_tokens": 10, "completion_tokens": 5}
        trace_id.cost = 0.0001
        
        # Get the URL
        url = get_trace_url(trace_id)
        
    print(f"\n🔗 Trace URL: {url}")
    print(f"✨ LANGFUSE OK — trace visible at: {url}")

if __name__ == "__main__":
    try:
        verify_langfuse()
    except Exception as e:
        print(f"❌ Langfuse verification failed: {str(e)}")
        print("\nEnsure you have LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_HOST set in your .env file.")
        sys.exit(1)
