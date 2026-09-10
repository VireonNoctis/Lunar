import { useState } from "react";
import { AlertTriangle } from "lucide-react";

interface ConfirmModalProps {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  danger?: boolean;
  requireReason?: boolean;
  onConfirm: (reason?: string) => void;
  onCancel: () => void;
}

export default function ConfirmModal({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  danger = false,
  requireReason = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  const [reason, setReason] = useState("");

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-3 sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="card max-h-[90vh] w-full max-w-md overflow-y-auto p-5 sm:p-6">
        <div className="flex items-start gap-3">
          <div
            className={`rounded-full p-2 ${danger ? "bg-red-100 text-red-600 dark:bg-red-950 dark:text-red-400" : "bg-lunar-100 text-lunar-600 dark:bg-lunar-950 dark:text-lunar-400"}`}
          >
            <AlertTriangle className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{title}</h2>
            {description ? (
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{description}</p>
            ) : null}
          </div>
        </div>

        {requireReason ? (
          <div className="mt-4">
            <label className="label" htmlFor="confirm-reason">
              Audit reason <span className="text-red-500">*</span>
            </label>
            <textarea
              id="confirm-reason"
              className="input"
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why is this action being taken?"
              aria-required="true"
            />
          </div>
        ) : null}

        <div className="mt-6 flex justify-end gap-3">
          <button type="button" className="btn-secondary" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className={danger ? "btn-danger" : "btn-primary"}
            onClick={() => onConfirm(requireReason ? reason : undefined)}
            disabled={requireReason && reason.trim().length < 3}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}