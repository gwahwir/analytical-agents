import { cancelTask } from "../hooks/useApi";
import { useState } from "react";

export default function TaskDetailDrawer({ task, onClose, onCancelled }) {
  const [cancelling, setCancelling] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);

  if (!task) return null;

  const canCancel = ["submitted", "working"].includes(task.state);

  const handleCancel = async () => {
    if (!confirmCancel) {
      setConfirmCancel(true);
      return;
    }
    setCancelling(true);
    try {
      await cancelTask(task.agent_id, task.task_id);
      onCancelled(task.task_id);
    } catch (err) {
      alert("Cancel failed: " + err.message);
    } finally {
      setCancelling(false);
      setConfirmCancel(false);
    }
  };

  const stateColor = {
    completed: "text-emerald-400 bg-emerald-500/10",
    working: "text-amber-400 bg-amber-500/10",
    submitted: "text-slate-400 bg-slate-500/10",
    canceled: "text-red-400 bg-red-500/10",
    failed: "text-red-400 bg-red-500/10",
    "input-required": "text-purple-400 bg-purple-500/10",
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-slate-900 border-l border-slate-700 p-6 overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-bold text-white">Task Detail</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white text-xl"
          >
            &times;
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="text-xs text-slate-500 uppercase">Task ID</label>
            <p className="text-sm font-mono text-slate-300">{task.task_id}</p>
          </div>

          <div>
            <label className="text-xs text-slate-500 uppercase">Agent</label>
            <p className="text-sm text-slate-300">{task.agent_id}</p>
          </div>

          <div>
            <label className="text-xs text-slate-500 uppercase">State</label>
            <p>
              <span
                className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
                  stateColor[task.state] || "text-slate-400"
                }`}
              >
                {task.state}
              </span>
            </p>
          </div>

          <div>
            <label className="text-xs text-slate-500 uppercase">Input</label>
            <div className="mt-1 rounded-md bg-slate-800 p-3 text-sm text-slate-300 whitespace-pre-wrap">
              {task.input_text || "—"}
            </div>
          </div>

          <div>
            <label className="text-xs text-slate-500 uppercase">Output</label>
            <div className="mt-1 rounded-md bg-slate-800 p-3 text-sm text-slate-300 whitespace-pre-wrap">
              {task.output_text || "—"}
            </div>
          </div>

          <div>
            <label className="text-xs text-slate-500 uppercase">Created</label>
            <p className="text-sm text-slate-400">
              {task.created_at
                ? new Date(task.created_at * 1000).toLocaleString()
                : "—"}
            </p>
          </div>

          {canCancel && (
            <div className="pt-4 border-t border-slate-700">
              <button
                onClick={handleCancel}
                disabled={cancelling}
                className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
                  confirmCancel
                    ? "bg-red-600 text-white hover:bg-red-500"
                    : "bg-slate-700 text-red-400 hover:bg-slate-600"
                } disabled:opacity-50`}
              >
                {cancelling
                  ? "Cancelling..."
                  : confirmCancel
                  ? "Click again to confirm"
                  : "Cancel Task"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
