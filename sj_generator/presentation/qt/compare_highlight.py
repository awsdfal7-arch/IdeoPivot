from __future__ import annotations


def compare_highlight_model_styles(
    *,
    model_sigs: dict[str, str],
    round_no: int,
    round_matched_count: int,
) -> dict[str, str]:
    del round_no
    non_empty = {key: sig for key, sig in model_sigs.items() if sig}
    empty_keys = {key for key, sig in model_sigs.items() if not sig}

    if len(non_empty) == len(model_sigs) and len(set(non_empty.values())) == 1:
        return {}

    if round_matched_count >= 2:
        freq: dict[str, int] = {}
        for sig in non_empty.values():
            freq[sig] = freq.get(sig, 0) + 1
        majority_sig = next((sig for sig, count in freq.items() if count >= 2), None)
        if majority_sig is None:
            return {
                key: ("yellow" if key in empty_keys else "red")
                for key in model_sigs.keys()
            }
        styles: dict[str, str] = {key: "yellow" for key in empty_keys}
        for key, sig in non_empty.items():
            if sig != majority_sig:
                styles[key] = "red"
        return styles

    styles = {key: "yellow" for key in empty_keys}
    if len(non_empty) >= 2 and len(set(non_empty.values())) == len(non_empty):
        for key in non_empty.keys():
            styles[key] = "red"
    return styles
