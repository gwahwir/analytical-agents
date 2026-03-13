import { useState } from "react";
import { dispatchTask } from "../hooks/useApi";

export default function TaskLauncher({ agents, onTaskCreated }) {
  const [agentId, setAgentId] = useState("");
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!agentId || !text.trim()) return;

    setLoading(true);
    setError(null);
    try {
      const result = await dispatchTask(agentId, text.trim());
      onTaskCreated(result);
      setText("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section>
      <h2 className="text-xl font-bold text-white mb-4">Launch Task</h2>
      <form onSubmit={handleSubmit} className="flex gap-3 items-end flex-wrap">
        <div className="flex-shrink-0">
          <label className="block text-xs text-slate-400 mb-1">Agent</label>
          <select
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            className="rounded-md bg-slate-800 border border-slate-700 text-white px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
          >
            <option value="">Select agent...</option>
            {agents
              .filter((a) => a.status === "online")
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
          </select>
        </div>

        <div className="flex-1 min-w-[200px]">
          <label className="block text-xs text-slate-400 mb-1">Prompt</label>
          <input
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Enter a task prompt..."
            className="w-full rounded-md bg-slate-800 border border-slate-700 text-white px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
          />
        </div>

        <button
          type="submit"
          disabled={loading || !agentId || !text.trim()}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? "Sending..." : "Send"}
        </button>
      </form>

      {error && <p className="text-red-400 text-sm mt-2">{error}</p>}
    </section>
  );
}
