"use client";

import { useState } from "react";
import { QueryResult, Conflict } from "@/types";
import ConflictBadge from "./ConflictBadge";
import TraceViewer from "./TraceViewer";

interface ResultCardProps {
  result: QueryResult;
}

const SECTION_HEADERS = new Set([
  "SUMMARY",
  "KEY FINDINGS",
  "CONFLICT ANALYSIS",
  "CONCLUSIONS",
  "REFERENCES",
]);

/** Render inline text, converting legacy [PaperN] tokens to pill badges. */
function InlineText({ text }: { text: string }) {
  const parts = text.split(/(\[Paper\d+\])/g);
  return (
    <>
      {parts.map((part, i) =>
        /^\[Paper\d+\]$/.test(part) ? (
          <span
            key={i}
            className="inline-flex items-center mx-0.5 px-1.5 py-0.5 rounded text-xs font-semibold bg-blue-900/60 text-blue-300 border border-blue-700"
          >
            {part}
          </span>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}

/** Render the content of one section: numbered items, reference entries, or plain paragraphs. */
function SectionContent({
  content,
  isRefs,
}: {
  content: string;
  isRefs: boolean;
}) {
  const blocks = content
    .split(/\n{2,}/)
    .map((b) => b.trim())
    .filter(Boolean);

  if (isRefs) {
    return (
      <div className="space-y-2 mt-2">
        {blocks.map((block, i) => (
          <p
            key={i}
            className="text-slate-400 text-sm leading-relaxed border-l-2 border-slate-600 pl-3"
          >
            {block}
          </p>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-3 mt-2">
      {blocks.map((block, i) => {
        const m = block.match(/^(\d+)\.\s+([\s\S]+)$/);
        if (m) {
          return (
            <div key={i} className="flex gap-3">
              <span className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-900/50 border border-blue-700 text-blue-300 text-xs font-bold flex items-center justify-center mt-0.5">
                {m[1]}
              </span>
              <p className="text-slate-200 text-sm leading-relaxed flex-1">
                <InlineText text={m[2]} />
              </p>
            </div>
          );
        }
        return (
          <p key={i} className="text-slate-200 text-sm leading-relaxed">
            <InlineText text={block} />
          </p>
        );
      })}
    </div>
  );
}

/**
 * Parse plain-text answer into structured sections.
 * ALL CAPS headers (SUMMARY, KEY FINDINGS, etc.) become styled h3 headings.
 * Numbered items get pill-number treatment. REFERENCES get citation styling.
 */
function AnswerText({ text }: { text: string }) {
  const lines = text.split("\n");
  const sections: Array<{ header: string | null; contentLines: string[] }> = [];
  let current: { header: string | null; contentLines: string[] } = {
    header: null,
    contentLines: [],
  };

  for (const line of lines) {
    if (SECTION_HEADERS.has(line.trim())) {
      if (current.header !== null || current.contentLines.some((l) => l.trim())) {
        sections.push(current);
      }
      current = { header: line.trim(), contentLines: [] };
    } else {
      current.contentLines.push(line);
    }
  }
  if (current.header !== null || current.contentLines.some((l) => l.trim())) {
    sections.push(current);
  }

  return (
    <div data-testid="answer-text" className="space-y-6">
      {sections.map((section, i) => (
        <div key={i}>
          {section.header && (
            <div className="flex items-center gap-3 mb-3">
              <h3 className="text-xs font-bold text-slate-300 uppercase tracking-widest whitespace-nowrap">
                {section.header}
              </h3>
              <div className="flex-1 border-t border-slate-700" />
            </div>
          )}
          <SectionContent
            content={section.contentLines.join("\n")}
            isRefs={section.header === "REFERENCES"}
          />
        </div>
      ))}
    </div>
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
