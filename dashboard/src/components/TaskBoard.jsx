const STATE_COLUMNS = [
  { key: "submitted", label: "Queued", color: "text-slate-400" },
  { key: "working", label: "Working", color: "text-amber-400" },
  { key: "input-required", label: "Input Required", color: "text-purple-400" },
  { key: "completed", label: "Done", color: "text-emerald-400" },
  { key: "canceled", label: "Cancelled", color: "text-red-400" },
  { key: "failed", label: "Failed", color: "text-red-400" },
];

export default function TaskBoard({ tasks, onSelectTask }) {
  const grouped = {};
  for (const col of STATE_COLUMNS) grouped[col.key] = [];
  for (const t of tasks) {
    if (grouped[t.state]) grouped[t.state].push(t);
    else if (grouped["failed"]) grouped["failed"].push(t);
  }

  return (
    <section>
      <h2 className="text-xl font-bold text-white mb-4">Active Tasks</h2>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {STATE_COLUMNS.map((col) => (
          <div key={col.key}>
            <div className="flex items-center gap-2 mb-2">
              <span className={`text-sm font-medium ${col.color}`}>
                {col.label}
              </span>
              <span className="text-xs text-slate-500 bg-slate-800 rounded-full px-1.5">
                {grouped[col.key].length}
              </span>
            </div>
            <div className="space-y-2">
              {grouped[col.key].map((task) => (
                <div
                  key={task.task_id}
                  onClick={() => onSelectTask(task)}
                  className="cursor-pointer rounded-md border border-slate-700 bg-slate-800 p-2.5 hover:border-indigo-500 transition-colors"
                >
                  <p className="text-xs text-slate-300 truncate">
                    {task.input_text}
                  </p>
                  <p className="text-xs text-slate-500 mt-1">
                    {task.agent_id}
                  </p>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
