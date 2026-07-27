"""Command-line interface for the public RACER-GT core."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd
from .core import (
    calibrate_overlap_graph,
    covariance_adjusted_consensus,
    create_balanced_design,
    create_chunk_windows,
    expand_request_manifest,
    run_replay,
)

def build_parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(prog="racergt")
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("design"); p.add_argument("--days",default="0,1,2,7,14,21,30"); p.add_argument("--streams",default="A,B,C"); p.add_argument("--replicates",type=int,default=2); p.add_argument("--output",required=True)
    p=sub.add_parser("manifest"); p.add_argument("--design",required=True); p.add_argument("--keyword",required=True); p.add_argument("--geo",default=""); p.add_argument("--historical-start",required=True); p.add_argument("--historical-end",required=True); p.add_argument("--window-days",type=int,default=180); p.add_argument("--step-days",type=int,default=60); p.add_argument("--output",required=True)
    p=sub.add_parser("fit"); p.add_argument("--input",required=True); p.add_argument("--output-dir",required=True)
    p=sub.add_parser("replay"); p.add_argument("--seed",type=int,default=42); p.add_argument("--output")
    return parser

def main(argv: list[str]|None=None) -> int:
    args=build_parser().parse_args(argv)
    if args.command=="design":
        frame=create_balanced_design(tuple(int(x) for x in args.days.split(",")),tuple(args.streams.split(",")),args.replicates)
        Path(args.output).parent.mkdir(parents=True,exist_ok=True); frame.to_csv(args.output,index=False)
    elif args.command=="manifest":
        design=pd.read_csv(args.design); windows=create_chunk_windows(args.historical_start,args.historical_end,window_days=args.window_days,step_days=args.step_days)
        manifest=expand_request_manifest(design,windows,keyword=args.keyword,geo=args.geo)
        Path(args.output).parent.mkdir(parents=True,exist_ok=True); manifest.to_csv(args.output,index=False)
    elif args.command=="fit":
        chunks=pd.read_csv(args.input); result=calibrate_overlap_graph(chunks); consensus=covariance_adjusted_consensus(result.reconstructed)
        out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
        result.reconstructed.to_csv(out/"reconstructed_pulls.csv",index=False); result.offsets.to_csv(out/"chunk_offsets.csv",index=False); result.edge_diagnostics.to_csv(out/"edge_diagnostics.csv",index=False); consensus.series.to_csv(out/"consensus_series.csv",index=False); consensus.weights.to_csv(out/"consensus_weights.csv",index=False)
    elif args.command=="replay":
        metrics=run_replay(args.seed); text=json.dumps(metrics,indent=2)
        if args.output: Path(args.output).write_text(text+"\n",encoding="utf-8")
        print(text)
    return 0
