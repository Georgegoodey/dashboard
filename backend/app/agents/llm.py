"""The only place a chat model is constructed. Everything else calls get_llm()."""
from app.core.config import settings


def get_llm():
    provider = settings.llm_provider.lower()
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            num_ctx=settings.llm_num_ctx,
            temperature=0,
            reasoning=False,  # no <think> blocks: faster, and nothing to strip from the answer
        )
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kwargs = {"api_key": settings.anthropic_api_key} if settings.anthropic_api_key else {}
        return ChatAnthropic(model=settings.llm_model, **kwargs)
    raise ValueError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Use 'anthropic' or 'ollama'.")
