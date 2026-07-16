import argparse
import json
import os
import time
from pathlib import Path
from typing import Optional


DEFAULT_INPUT_PATH = Path(__file__).with_name("checking_inputs_with_rag.json")
DEFAULT_OUTPUT_PATH = Path(__file__).with_name("checking_outputs.json")

METRIC_NAMES = ("all_metrics", "overall_metrics", "retriever_metrics", "generator_metrics")


def load_ragchecker_dependencies(metrics_name: str):
    from ragchecker import RAGChecker, RAGResults
    from ragchecker.metrics import (
        all_metrics,
        generator_metrics,
        overall_metrics,
        retriever_metrics,
    )

    metric_groups = {
        "all_metrics": all_metrics,
        "overall_metrics": overall_metrics,
        "retriever_metrics": retriever_metrics,
        "generator_metrics": generator_metrics,
    }
    return RAGChecker, RAGResults, metric_groups[metrics_name]


def save_results(rag_results, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(rag_results, "to_json"):
        raw = rag_results.to_json()
        try:
            parsed = json.loads(raw)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(parsed, f, indent=2, ensure_ascii=False)
            return
        except json.JSONDecodeError:
            pass

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(str(rag_results))


def build_retrying_litellm_func(model_name: str):
    sleep_seconds = float(os.getenv("RAGCHECKER_LLM_SLEEP_SECONDS", "6"))
    max_retries = int(os.getenv("RAGCHECKER_LLM_MAX_RETRIES", "8"))
    max_tokens = int(os.getenv("RAGCHECKER_LLM_MAX_TOKENS", "512"))

    def call_llm(prompts):
        import litellm

        if os.getenv("RAGCHECKER_LITELLM_DEBUG", "0") == "1":
            litellm._turn_on_debug()

        responses = []
        for prompt in prompts:
            for attempt in range(max_retries):
                try:
                    response = litellm.completion(
                        model=model_name,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0,
                        max_tokens=max_tokens,
                    )
                    content = response.choices[0].message.content or ""
                    responses.append(content)
                    if sleep_seconds > 0:
                        time.sleep(sleep_seconds)
                    break
                except Exception as exc:
                    message = str(exc).lower()
                    is_rate_limit = (
                        "ratelimit" in message
                        or "rate limit" in message
                        or "rate_limit" in message
                        or "tpm" in message
                    )
                    if not is_rate_limit or attempt == max_retries - 1:
                        raise

                    wait_seconds = sleep_seconds * (attempt + 1)
                    print(
                        f"Rate limit from {model_name}; waiting {wait_seconds:.1f}s "
                        f"before retry {attempt + 2}/{max_retries}."
                    )
                    time.sleep(wait_seconds)
        return responses

    return call_llm


def run_ragchecker(
    input_path: Path = DEFAULT_INPUT_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    metrics_name: str = "all_metrics",
    extractor_name: Optional[str] = None,
    checker_name: Optional[str] = None,
):
    extractor_name = (
        extractor_name
        or os.getenv("RAGCHECKER_EXTRACTOR")
        or os.getenv("RAGCHECKER_MODEL")
        or "groq/llama-3.1-8b-instant"
    )
    checker_name = (
        checker_name
        or os.getenv("RAGCHECKER_CHECKER")
        or os.getenv("RAGCHECKER_MODEL")
        or extractor_name
    )
    RAGChecker, RAGResults, metrics = load_ragchecker_dependencies(metrics_name)

    with open(input_path, "r", encoding="utf-8") as f:
        rag_results = RAGResults.from_json(f.read())

    batch_size_extractor = int(os.getenv("RAGCHECKER_BATCH_SIZE_EXTRACTOR", "1"))
    batch_size_checker = int(os.getenv("RAGCHECKER_BATCH_SIZE_CHECKER", "1"))
    use_retrying_llm = os.getenv("RAGCHECKER_USE_RETRYING_LLM", "1") == "1"

    if use_retrying_llm:
        evaluator = RAGChecker(
            custom_llm_api_func=build_retrying_litellm_func(extractor_name),
            batch_size_extractor=batch_size_extractor,
            batch_size_checker=batch_size_checker,
        )
    else:
        evaluator = RAGChecker(
            extractor_name=extractor_name,
            checker_name=checker_name,
            batch_size_extractor=batch_size_extractor,
            batch_size_checker=batch_size_checker,
        )

    evaluator.evaluate(rag_results, metrics)
    save_results(rag_results, output_path)
    print(rag_results)
    print(f"Saved RAGChecker results to: {output_path}")


def main(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description="Run RAGChecker on generated VR RAG outputs.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--metrics", choices=METRIC_NAMES, default="all_metrics")
    parser.add_argument("--extractor-name", default=None)
    parser.add_argument("--checker-name", default=None)
    args = parser.parse_args(argv)

    run_ragchecker(
        input_path=args.input,
        output_path=args.output,
        metrics_name=args.metrics,
        extractor_name=args.extractor_name,
        checker_name=args.checker_name,
    )


if __name__ == "__main__":
    main()
