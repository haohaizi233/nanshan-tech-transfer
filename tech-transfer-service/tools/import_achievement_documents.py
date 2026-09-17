"""把 PPT/PDF 成果资料写入可审核 staging。用法见 --help。"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.achievement.importer import extract_document_records, stage_document

parser = argparse.ArgumentParser(description="PPT/PDF 成果导入 staging；不会自动创建或发布成果")
parser.add_argument("source")
parser.add_argument("--created-by", type=int, default=None)
parser.add_argument("--source-org", default=None)
parser.add_argument("--dry-run", action="store_true", help="只解析并输出统计，不创建 staging 批次或媒体文件")
args = parser.parse_args()
if args.dry_run:
    records = extract_document_records(args.source)
    print(json.dumps({
        "source": str(Path(args.source)),
        "total": len(records),
        "staged": sum(not item["errors"] for item in records),
        "failed": sum(bool(item["errors"]) for item in records),
        "candidateImages": sum(len(item.get("images", [])) for item in records),
        "errors": [
            {"sourcePageOrSlide": item["sourcePageOrSlide"], "errors": item["errors"]}
            for item in records if item["errors"]
        ],
    }, ensure_ascii=False, indent=2))
else:
    print(json.dumps(stage_document(args.source, args.created_by, args.source_org), ensure_ascii=False, indent=2))
