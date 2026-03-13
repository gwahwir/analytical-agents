import { useState } from "react";

export default function TaskHistory({ tasks, onSelectTask }) {
  const [search, setSearch] = useState("");
  const [filterState, setFilterState] = useState("");

  const filtered = tasks.filter((t) => {
    const matchesSearch =
      !search ||
      t.input_text.toLowerCase().includes(search.toLowerCase()) ||
      t.agent_id.toLowerCase().includes(search.toLowerCase()) ||
      t.task_id.toLowerCase().includes(search.toLowerCase());
    const matchesState = !filterState || t.state === filterState;
    return matchesSearch && matchesState;
  });

  const stateColor = (state) => {
    const colors = {
      completed: "text-emerald-400",
      working: "text-amber-400",
      submitted: "text-slate-400",
      canceled: "text-red-400",
      failed: "text-red-400",
      "input-required": "text-purple-400",
    };
    return colors[state] || "text-slate-400";
  };

  return (
    <section>
      <h2 className="text-xl font-bold text-white mb-4">Task History</h2>

      <div className="flex gap-3 mb-3 flex-wrap">
        <input
          type="text"
          placeholder="Search tasks..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 min-w-[200px] rounded-md bg-slate-800 border border-slate-700 text-white px-3 py-1.5 text-sm focus:outline-none focus:border-indigo-500"
        />
        <select
          value={filterState}
          onChange={(e) => setFilterState(e.target.value)}
          className="rounded-md bg-slate-800 border border-slate-700 text-white px-3 py-1.5 text-sm focus:outline-none focus:border-indigo-500"
        >
          <option value="">All states</option>
          <option value="completed">Completed</option>
          <option value="working">Working</option>
          <option value="submitted">Submitted</option>
          <option value="canceled">Cancelled</option>
          <option value="failed">Failed</option>
        </select>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-700">
        <table className="w-full text-sm text-left">
          <thead className="bg-slate-800 text-slate-400 text-xs uppercase">
            <tr>
              <th className="px-4 py-2">Task ID</th>
              <th className="px-4 py-2">Agent</th>
              <th className="px-4 py-2">Input</th>
              <th className="px-4 py-2">State</th>
              <th className="px-4 py-2">Time</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((task) => (
              <tr
                key={task.task_id}
                onClick={() => onSelectTask(task)}
                className="border-t border-slate-700 hover:bg-slate-800/50 cursor-pointer"
              >
                <td className="px-4 py-2 font-mono text-xs text-slate-400">
                  {task.task_id.slice(0, 8)}...
                </td>
                <td className="px-4 py-2 text-slate-300">{task.agent_id}</td>
                <td className="px-4 py-2 text-slate-300 max-w-[200px] truncate">
                  {task.input_text}
                </td>
                <td className={`px-4 py-2 font-medium ${stateColor(task.state)}`}>
                  {task.state}
                </td>
                <td className="px-4 py-2 text-slate-500 text-xs">
                  {new Date(task.created_at * 1000).toLocaleString()}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-4 text-center text-slate-500">
                  No tasks found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
