"""Shape-gate a Surya results.json before accepting it as a witness artifact.

Used before any results.json arriving from the remote box (holos) is trusted -- a truncated
rsync, a version-mismatched surya_ocr, or a genuinely different JSON shape must fail loudly here
rather than corrupt merge-canonical.py's output silently.

Usage: validate-surya-json.py <results.json>
Exit 0 and silent on success. Exit 1 with a message on stderr on any shape violation.
"""

import json
import sys


def fail(msg):
    print(f"[validate-surya-json] {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) != 2:
        print("Usage: validate-surya-json.py <results.json>", file=sys.stderr)
        sys.exit(2)

    path = sys.argv[1]

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        fail(f"{path}: not found")
    except json.JSONDecodeError as e:
        fail(f"{path}: not valid JSON ({e})")

    if not isinstance(data, dict) or not data:
        fail(f"{path}: top level must be a non-empty object keyed by stem")

    for stem, content_list in data.items():
        if not isinstance(content_list, list) or not content_list:
            fail(f"{path}: '{stem}' must map to a non-empty list of page blocks")

        for i, block in enumerate(content_list):
            if not isinstance(block, dict):
                fail(f"{path}: '{stem}'[{i}] is not an object")
            if "page" in block and not isinstance(block["page"], int):
                fail(f"{path}: '{stem}'[{i}].page must be an int if present")
            if "text_lines" not in block:
                fail(f"{path}: '{stem}'[{i}] missing 'text_lines'")
            if not isinstance(block["text_lines"], list):
                fail(f"{path}: '{stem}'[{i}].text_lines must be a list")

            for j, line in enumerate(block["text_lines"]):
                if not isinstance(line, dict):
                    fail(f"{path}: '{stem}'[{i}].text_lines[{j}] is not an object")
                if "text" not in line or not isinstance(line["text"], str):
                    fail(f"{path}: '{stem}'[{i}].text_lines[{j}] missing string 'text'")
                if "bbox" not in line or not (
                    isinstance(line["bbox"], list) and len(line["bbox"]) == 4
                ):
                    fail(f"{path}: '{stem}'[{i}].text_lines[{j}] missing 4-element 'bbox'")
                if not all(isinstance(v, (int, float)) for v in line["bbox"]):
                    fail(f"{path}: '{stem}'[{i}].text_lines[{j}].bbox must be all numbers")
                if "confidence" in line and line["confidence"] is not None:
                    c = line["confidence"]
                    if not isinstance(c, (int, float)) or not (0.0 <= c <= 1.0):
                        fail(
                            f"{path}: '{stem}'[{i}].text_lines[{j}].confidence"
                            f" must be a number in [0,1]"
                        )

            if "image_bbox" in block and not (
                isinstance(block["image_bbox"], list) and len(block["image_bbox"]) == 4
            ):
                fail(f"{path}: '{stem}'[{i}].image_bbox must be a 4-element list if present")

    sys.exit(0)


if __name__ == "__main__":
    main()
