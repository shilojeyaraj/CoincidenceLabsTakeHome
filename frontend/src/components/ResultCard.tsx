"use client";

import { useState } from "react";
import { QueryResult, Conflict } from "@/types";
import ConflictBadge from "./ConflictBadge";
import TraceViewer from "./TraceViewer";

interface ResultCardProps {
  result: QueryResult;
}

/** Parse [PaperN] citations and render them as inline blue pill badges. */
function AnswerText({ text }: { text: string }) {
  const parts = text.split(/(\[Paper\d+\])/g);

  return (
    <p data-testid="answer-text" className="text-slate-200 leading-relaxed text-sm">
      {parts.map((part, i) => {
        if (/^\[Paper\d+\]$/.test(part)) {
          return (
            <span
              key={i}
              className="inline-flex items-center mx-0.5 px-1.5 py-0.5 rounded text-xs font-semibold bg-blue-900/60 text-blue-300 border border-blue-700"
            >
              {part}
            </span>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </p>
  );
}

function ConflictItem({ conflict }: { conflict: Conflict }) {
  const [showMore, setShowMore] = useState(false);
  const MAX_CHARS = 200;
  const truncated =
    conflict.reasoning.length > MAX_CHARS && !showMore;
  const displayReasoning = truncated
    ? conflict.reasoning.slice(0, MAX_CHARS) + "…"
    : conflict.reasoning;

  return (
    <div
      data-testid="conflict-item"
      className="bg-slate-800/60 border border-slate-700 rounded-lg p-4 space-y-2"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <ConflictBadge conflictType={conflict.conflict_type} />
          <span className="text-slate-200 font-medium text-sm">
            {conflict.property}
          </span>
        </div>
      </div>

      <p className="text-slate-400 text-sm leading-relaxed">
        {displayReasoning}
        {conflict.reasoning.length > MAX_CHARS && (
          <button
            onClick={() => setShowMore((prev) => !prev)}
            className="ml-1 text-blue-400 hover:text-blue-300 text-xs font-medium"
          >
            {showMore ? "show less" : "show more"}
          </button>
        )}
      </p>

      {conflict.resolution && (
        <p className="text-slate-500 text-xs italic">
          Resolution: {conflict.resolution}
        </p>
      )}

      {conflict.papers_involved.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {conflict.papers_involved.map((paperId) => (
            <span
              key={paperId}
              className="px-2 py-0.5 text-xs rounded-full bg-slate-700 text-slate-300 border border-slate-600"
            >
              {paperId}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ResultCard({ result }: ResultCardProps) {
  const hasConflicts = result.conflicts.length > 0;

  return (
    <div
      data-testid="result-card"
      className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden shadow-xl space-y-0"
    >
      {/* Answer Section */}
      <div className="p-6 border-b border-slate-700">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
          Answer
        </h2>
        <AnswerText text={result.answer} />
      </div>

      {/* Context Expansion Banner */}
      {result.context_expansion_triggered && (
        <div
          data-testid="expansion-banner"
          className="px-6 py-3 bg-orange-900/30 border-b border-orange-800/50 flex items-center gap-2"
        >
          <span className="text-base" aria-hidden="true">
            ⚡
          </span>
          <p className="text-orange-300 text-sm font-medium">
            Context expansion triggered — additional chunks fetched for
            CONCEPTUAL conflicts
          </p>
        </div>
      )}

      {/* Conflicts Section */}
      {hasConflicts && (
        <div className="p-6 border-b border-slate-700 space-y-3">
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
              Detected Conflicts
            </h2>
            <span className="px-2 py-0.5 text-xs rounded-full bg-slate-700 text-slate-300 font-medium">
              {result.conflicts.length}
            </span>
          </div>
          <div className="space-y-3">
            {result.conflicts.map((conflict, index) => (
              <ConflictItem
                key={`${conflict.property}-${index}`}
                conflict={conflict}
              />
            ))}
          </div>
        </div>
      )}

      {/* Papers Cited Section */}
      {result.papers_cited.length > 0 && (
        <div className="p-6 border-b border-slate-700 space-y-3">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
            Papers Cited
          </h2>
          <ul className="space-y-1.5">
            {result.papers_cited.map((paperId) => (
              <li key={paperId} className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-500 flex-shrink-0" />
                <span className="text-slate-300 text-sm font-mono">
                  {paperId}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Trace Viewer Section */}
      <div className="p-6">
        <TraceViewer trace={result.trace} />
      </div>
    </div>
  );
}
