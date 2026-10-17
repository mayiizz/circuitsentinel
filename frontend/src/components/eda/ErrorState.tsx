import { AlertTriangle } from "lucide-react";

export function ErrorState({ title, message }: { title: string; message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-danger/40 bg-danger/5 px-4 py-3 text-xs">
      <AlertTriangle size={14} className="mt-0.5 shrink-0 text-danger" />
      <div>
        <p className="font-medium text-danger">{title}</p>
        <p className="mt-1 text-muted-foreground">{message}</p>
      </div>
    </div>
  );
}
