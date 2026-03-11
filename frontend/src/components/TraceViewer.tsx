"use client";

import { useState } from "react";
import { TraceStep } from "@/types";

interface TraceViewerProps {
  trace: TraceStep[];
}

function TraceStepItem({ step }: { step: TraceStep }) {
  const [expanded, setExpanded] = useState(false);
  const isContextExpansion = step.step === "ConflictAgent.ContextExpansion";

  return (
    <div
      data-testid="trace-step"
      className={`rounded-lg border bg-slate-800/50 overflow-hidden ${
        isContextExpansion
          ? "border-orange-600 border-l-4 border-l-orange-500"
          : "border-slate-700"
      }`}
    >
      <button
        onClick={() => setExpanded((prev) => !prev)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-slate-700/30 transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-slate-100 font-semibold text-sm truncate">
            {step.agent}
          </span>
          <span className="text-slate-500 text-xs">·</span>
          <span className="text-slate-400 text-xs truncate">{step.step}</span>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0 ml-2">
          <span className="text-slate-400 text-xs font-mono">
            {step.latency_ms}ms
          </span>
          <svg
            className={`w-4 h-4 text-slate-500 transition-transform ${expanded ? "rotate-180" : ""}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-1 border-t border-slate-700 space-y-3">
          <div>
            <p className="text-xs text-slate-500 uppercase tracking-wide font-semibold mb-1">
              Input
            </p>
            <p className="text-sm text-slate-300 leading-relaxed">
              {step.input_summary}
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-500 uppercase tracking-wide font-semibold mb-1">
              Output
            </p>
            <p className="text-sm text-slate-300 leading-relaxed">
              {step.output_summary}
            </p>
          </div>
          <div className="flex items-center gap-4 pt-1">
            <span className="text-xs text-slate-500">
              <span className="text-slate-400">{step.tokens_used}</span> tokens
            </span>
            <span className="text-xs text-slate-500">
              {new Date(step.timestamp).toLocaleTimeString()}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

export default function TraceViewer({ trace }: TraceViewerProps) {
  const [showTrace, setShowTrace] = useState(false);

  const totalTokens = trace.reduce((sum, s) => sum + s.tokens_used, 0);
  const totalLatency = trace.reduce((sum, s) => sum + s.latency_ms, 0);

  return (
    <div data-testid="trace-viewer" className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wide">
            Agent Trace
          </h3>
          {showTrace && (
            <div className="flex items-center gap-3 text-xs text-slate-500">
              <span>
                <span className="text-slate-400">{trace.length}</span> steps
              </span>
              <span>
                <span className="text-slate-400">
                  {totalTokens.toLocaleString()}
                </span>{" "}
                tokens
              </span>
              <span>
                <span className="text-slate-400">{totalLatency}ms</span> total
              </span>
            </div>
          )}
        </div>
        <button
          data-testid="trace-toggle"
          onClick={() => setShowTrace((prev) => !prev)}
          className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors font-medium"
        >
          {showTrace ? "Hide Trace" : "Show Trace"}
          <svg
            className={`w-3.5 h-3.5 transition-transform ${showTrace ? "rotate-180" : ""}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </button>
      </div>

      {showTrace && (
        <div className="space-y-2">
          {trace.map((step, index) => (
            <TraceStepItem key={`${step.agent}-${step.step}-${index}`} step={step} />
          ))}
        </div>
      )}
    </div>
  );
}
