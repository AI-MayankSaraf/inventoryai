"use client";

import * as React from "react";
import { ArrowDown, ArrowUp, Check, Pencil, Plus, Trash2, X } from "lucide-react";

import { FormError } from "@/components/common/async-state";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { SectionCard } from "@/components/common/section-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useAddListItem,
  useCompanyLists,
  useDeleteListItem,
  useUpdateListItem,
} from "@/hooks/use-admin";
import { usePermission } from "@/hooks/use-session";
import type { adminApi } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Settings > Lists: the pick-lists behind the PO form's payment and delivery
 * terms and the supplier form's type. Each company keeps its own.
 *
 * Records copy the chosen text, so renaming or removing a value here never
 * changes a saved PO or supplier. Switching a value off hides it from the
 * forms while keeping it available to restore.
 */
export function CompanyListsCard() {
  const canManage = usePermission("company.manage");
  const lists = useCompanyLists();
  const refresh = lists.refresh;

  return (
    <div data-testid="company-lists-card">
      <SectionCard title="Lists" description="The choices offered in purchase orders and supplier forms">
        {!lists.data ? (
          <p className="p-4 text-caption text-muted-foreground">Loading…</p>
        ) : (
          <Tabs defaultValue={lists.data[0]?.key} className="p-4">
            <TabsList>
              {lists.data.map((list) => (
                <TabsTrigger key={list.key} value={list.key}>
                  {list.label}
                </TabsTrigger>
              ))}
            </TabsList>
            {lists.data.map((list) => (
              <TabsContent key={list.key} value={list.key} className="mt-3">
                <ListEditor list={list} canManage={canManage} onChanged={refresh} />
              </TabsContent>
            ))}
          </Tabs>
        )}
      </SectionCard>
    </div>
  );
}

function ListEditor({
  list,
  canManage,
  onChanged,
}: {
  list: adminApi.CompanyList;
  canManage: boolean;
  onChanged: () => void;
}) {
  const [newValue, setNewValue] = React.useState("");
  const [editing, setEditing] = React.useState<{ id: string; value: string } | null>(null);
  const [deleting, setDeleting] = React.useState<adminApi.CompanyListItem | null>(null);

  const add = useAddListItem(() => {
    setNewValue("");
    onChanged();
  });
  const update = useUpdateListItem(onChanged);
  const remove = useDeleteListItem(onChanged);

  const items = list.items;

  async function move(index: number, delta: -1 | 1) {
    const target = index + delta;
    if (target < 0 || target >= items.length) return;
    const reordered = [...items];
    [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
    // Renumber in steps of 10 and send only the rows whose position moved.
    for (const [i, item] of reordered.entries()) {
      if (item.sortOrder !== i * 10) await update.run({ id: item.id, patch: { sortOrder: i * 10 } });
    }
  }

  async function saveEdit() {
    if (!editing) return;
    const result = await update.run({ id: editing.id, patch: { value: editing.value } });
    if (result) setEditing(null);
  }

  const error = add.error ?? update.error ?? remove.error;

  return (
    <div className="space-y-3">
      <ul className="divide-y divide-border rounded-lg border border-border" data-testid={`list-${list.key}`}>
        {items.length === 0 && <li className="px-3 py-2.5 text-caption text-muted-foreground">No values yet.</li>}
        {items.map((item, index) => (
          <li key={item.id} className="flex items-center gap-2 px-3 py-2">
            {editing?.id === item.id ? (
              <form
                className="flex flex-1 items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  void saveEdit();
                }}
              >
                <Input
                  autoFocus
                  value={editing.value}
                  onChange={(e) => setEditing({ id: item.id, value: e.target.value })}
                  className="h-8"
                  aria-label={`Rename ${item.value}`}
                />
                <Button type="submit" size="icon" variant="ghost" className="size-8" aria-label="Save">
                  <Check className="size-4" />
                </Button>
                <Button type="button" size="icon" variant="ghost" className="size-8" aria-label="Cancel" onClick={() => setEditing(null)}>
                  <X className="size-4" />
                </Button>
              </form>
            ) : (
              <span className={cn("flex-1 text-[13.5px]", !item.isActive && "text-muted-foreground line-through")}>
                {item.value}
              </span>
            )}
            {canManage && editing?.id !== item.id && (
              <div className="flex items-center gap-1">
                <Button size="icon" variant="ghost" className="size-8" aria-label={`Move ${item.value} up`}
                  disabled={index === 0 || update.isPending} onClick={() => void move(index, -1)}>
                  <ArrowUp className="size-3.5" />
                </Button>
                <Button size="icon" variant="ghost" className="size-8" aria-label={`Move ${item.value} down`}
                  disabled={index === items.length - 1 || update.isPending} onClick={() => void move(index, 1)}>
                  <ArrowDown className="size-3.5" />
                </Button>
                <Button size="icon" variant="ghost" className="size-8" aria-label={`Rename ${item.value}`}
                  onClick={() => setEditing({ id: item.id, value: item.value })}>
                  <Pencil className="size-3.5" />
                </Button>
                <Switch
                  checked={item.isActive}
                  onCheckedChange={(checked) => void update.run({ id: item.id, patch: { isActive: checked } })}
                  aria-label={`${item.value} offered in forms`}
                />
                <Button size="icon" variant="ghost" className="size-8 text-destructive" aria-label={`Delete ${item.value}`}
                  onClick={() => setDeleting(item)}>
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>

      {canManage && (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void add.run({ listKey: list.key, value: newValue });
          }}
        >
          <Input
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            placeholder={`Add to ${list.label.toLowerCase()}`}
            aria-label={`New value for ${list.label}`}
          />
          <Button type="submit" variant="outline" disabled={add.isPending || !newValue.trim()}>
            <Plus className="size-4" /> Add
          </Button>
        </form>
      )}
      <p className="text-caption text-muted-foreground">
        Switched-off values stay on records that already use them but are no longer offered.
      </p>
      {error && <FormError message={error} />}

      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Remove "${deleting?.value ?? ""}"?`}
        description="Records that already use it keep it. To hide it without removing it, switch it off instead."
        confirmLabel="Remove"
        tone="destructive"
        onConfirm={async () => {
          if (deleting) await remove.run(deleting.id);
        }}
      />
    </div>
  );
}
