import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Select } from "@/components/ui/input";
import { api } from "@/services/api";

interface Member { id: number; name: string; email: string; is_owner: boolean }

/** Transfert de propriété : réservé à `workspace.manage`, vers un membre actif (contrôlé par Django). */
export function TransferOwnershipDialog({ workspaceId, open, onOpenChange }: { workspaceId: number; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const [userId, setUserId] = useState("");
  const members = useQuery({
    queryKey: ["workspaces", workspaceId, "members"],
    queryFn: ({ signal }) => api<Member[]>(`workspaces/${workspaceId}/members/`, { signal }),
    enabled: open,
  });
  const transfer = useMutation({
    mutationFn: () => api<{ owner_name: string }>(`workspaces/${workspaceId}/transfer-ownership/`, { method: "POST", body: { user_id: Number(userId) } }),
    onSuccess: (r) => {
      toast.success(`Propriété transférée à ${r.owner_name}.`);
      void qc.invalidateQueries({ queryKey: ["workspaces"] });
      onOpenChange(false);
    },
    onError: (e) => toast.error(e.message),
  });
  const candidates = members.data?.filter((m) => !m.is_owner) ?? [];
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Transférer la propriété"
      description="Le nouveau propriétaire obtient tous les droits d'administration. Vous conservez votre rôle actuel.">
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (userId) transfer.mutate(); }}>
        <Field id="new-owner" label="Nouveau propriétaire *">
          <Select id="new-owner" value={userId} onChange={(e) => setUserId(e.target.value)} disabled={members.isPending}>
            <option value="">{members.isPending ? "Chargement…" : "Sélectionner un membre"}</option>
            {candidates.map((m) => <option key={m.id} value={m.id}>{m.name} — {m.email}</option>)}
          </Select>
        </Field>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
          <Button type="submit" variant="destructive" disabled={!userId || transfer.isPending}>Transférer</Button>
        </div>
      </form>
    </Dialog>
  );
}
