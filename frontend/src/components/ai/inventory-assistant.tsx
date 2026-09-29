"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Brain, Database, Send, Sparkles, User } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAssistant, useAssistantSuggestions } from "@/hooks/use-documents";
import { cn } from "@/lib/utils";
import type { AssistantAnswer } from "@/types";

interface Turn {
  id: string;
  question: string;
  answer: AssistantAnswer | null;
}

let nextId = 1;

export function InventoryAssistant() {
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [draft, setDraft] = React.useState("");
  const endRef = React.useRef<HTMLDivElement>(null);
  const assistant = useAssistant();
  // One example per kind of question the backend answers, served by it —
  // so a chip can never offer a question the service cannot handle.
  const suggestions = useAssistantSuggestions().data ?? [];
  const thinking = assistant.isPending;

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, thinking]);

  async function ask(question: string) {
    const trimmed = question.trim();
    if (!trimmed || thinking) return;

    const id = String(nextId++);
    setTurns((prev) => [...prev, { id, question: trimmed, answer: null }]);
    setDraft("");

    const answer = await assistant.run(trimmed);
    setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, answer: answer ?? null } : t)));
  }

  return (
    <div className="flex flex-col gap-4">
      {/* How it works — keeps the AI honest about what it can do */}
      <div className="rounded-xl border border-ai-border/60 bg-ai-subtle/60 px-4 py-3">
        <p className="flex items-center gap-2 text-[13px] font-medium text-ai-subtle-foreground">
          <Sparkles className="size-4" />
          How your question is answered
        </p>
        <ol className="mt-2.5 grid gap-2 sm:grid-cols-3">
          {[
            { icon: Brain, label: "Your words are matched to an intent", detail: "by keyword rules, not a language model" },
            { icon: Database, label: "Your data is queried", detail: "read-only, through the app" },
            { icon: Sparkles, label: "The answer is shown", detail: "with the query that produced it" },
          ].map((step, index) => {
            const Icon = step.icon;
            return (
              <li key={step.label} className="flex items-start gap-2.5">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-card text-ai">
                  <Icon className="size-3.5" strokeWidth={2} />
                </span>
                <span className="min-w-0">
                  <span className="block text-[12.5px] font-medium text-foreground">
                    {index + 1}. {step.label}
                  </span>
                  <span className="block text-[11.5px] text-muted-foreground">{step.detail}</span>
                </span>
              </li>
            );
          })}
        </ol>
      </div>

      <div className="flex min-h-[420px] flex-col rounded-xl border border-border bg-card">
        <div className="flex-1 space-y-5 overflow-y-auto p-4">
          {turns.length === 0 && !thinking && (
            <div className="flex h-full flex-col items-center justify-center py-10 text-center">
              <span className="flex size-11 items-center justify-center rounded-xl bg-ai-subtle text-ai">
                <Sparkles className="size-5" strokeWidth={1.9} />
              </span>
              <p className="mt-3.5 text-section text-foreground">Ask about your inventory</p>
              <p className="mt-1 max-w-[420px] text-body text-muted-foreground">
                Plain English works — product names, godowns, suppliers or a date range.
              </p>
            </div>
          )}

          {turns.map((turn) => (
            <div key={turn.id} className="space-y-3">
              {/* Question */}
              <div className="flex items-start gap-3">
                <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                  <User className="size-3.5" strokeWidth={2} />
                </span>
                <p className="max-w-[760px] pt-0.5 text-[14px] font-medium text-foreground">
                  {turn.question}
                </p>
              </div>

              {/* Answer */}
              {turn.answer && (
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-ai-subtle text-ai">
                    <Sparkles className="size-3.5" strokeWidth={2} />
                  </span>

                  <div className="min-w-0 max-w-[760px] flex-1 space-y-2.5">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px]">
                      <span className="text-muted-foreground">
                        Understood as:{" "}
                        <span className="font-medium text-foreground">{turn.answer.intent}</span>
                      </span>
                      <span className="flex items-center gap-1 text-muted-foreground">
                        <Database className="size-3" />
                        {/* The query that was actually run, so the number is checkable. */}
                        {turn.answer.source}
                      </span>
                    </div>

                    <p className="text-[14px] leading-relaxed text-foreground">
                      {turn.answer.answer}
                    </p>

                    {turn.answer.breakdown && (
                      <ul className="grid gap-1.5 rounded-lg border border-border bg-muted/40 p-3 sm:grid-cols-2">
                        {turn.answer.breakdown.map((row) => (
                          <li
                            key={row.label}
                            className="flex items-center justify-between gap-3 text-[13px]"
                          >
                            <span className="text-muted-foreground">{row.label}</span>
                            <span
                              className={cn(
                                "font-medium tabular",
                                row.muted ? "text-muted-foreground" : "text-foreground",
                              )}
                            >
                              {row.value}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}

                    {turn.answer.table && (
                      <div className="overflow-hidden rounded-lg border border-border">
                        <Table>
                          <TableHeader>
                            <TableRow className="hover:bg-transparent">
                              {turn.answer.table.columns.map((col, i) => (
                                <TableHead
                                  key={col}
                                  className={cn(i === 0 && "pl-3", i > 0 && "text-right")}
                                >
                                  {col}
                                </TableHead>
                              ))}
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {turn.answer.table.rows.map((row, rowIndex) => (
                              <TableRow key={rowIndex}>
                                {row.map((cell, i) => (
                                  <TableCell
                                    key={i}
                                    className={cn(
                                      i === 0
                                        ? "pl-3 font-medium text-foreground"
                                        : "text-right text-muted-foreground tabular",
                                    )}
                                  >
                                    {cell}
                                  </TableCell>
                                ))}
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    )}

                    {turn.answer.link && (
                      <Button variant="outline" size="sm" asChild>
                        <Link href={turn.answer.link.href}>
                          {turn.answer.link.label}
                          <ArrowRight />
                        </Link>
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}

          {thinking && (
            <div className="flex items-center gap-3">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-ai-subtle text-ai">
                <Sparkles className="size-3.5 animate-pulse" strokeWidth={2} />
              </span>
              <span className="text-[13px] text-muted-foreground">
                Working out what to look up…
              </span>
            </div>
          )}

          <div ref={endRef} />
        </div>

        {/* Composer */}
        <div className="border-t border-border p-3">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              ask(draft);
            }}
            className="flex items-center gap-2"
          >
            <Input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="e.g. How many Pigeon 5L cookers are in stock?"
              className="h-10"
            />
            <Button type="submit" size="lg" disabled={!draft.trim() || thinking}>
              <Send />
              Ask
            </Button>
          </form>

          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {suggestions.map((question) => (
              <button
                key={question}
                type="button"
                onClick={() => ask(question)}
                disabled={thinking}
                className="rounded-full border border-border bg-card px-2.5 py-1 text-[12px] text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary-subtle/60 hover:text-primary-subtle-foreground disabled:opacity-50"
              >
                {question}
              </button>
            ))}
          </div>
        </div>
      </div>

      <p className="text-caption text-muted-foreground">
        The assistant matches your question to one of a fixed set of queries over your own data.
        It is not a language model, it never runs SQL of its own, and it cannot change stock,
        orders or prices.
      </p>
    </div>
  );
}
