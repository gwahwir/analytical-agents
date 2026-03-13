import { useState, useEffect, useCallback } from "react";
import AgentPanel from "./components/AgentPanel";
import TaskLauncher from "./components/TaskLauncher";
import TaskBoard from "./components/TaskBoard";
import TaskHistory from "./components/TaskHistory";
import TaskDetailDrawer from "./components/TaskDetailDrawer";
import { fetchAgents, fetchTasks } from "./hooks/useApi";

function App() {
  const [agents, setAgents] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [selectedTask, setSelectedTask] = useState(null);
  const [tab, setTab] = useState("board");

  const loadAgents = useCallback(() => {
    fetchAgents().then(setAgents).catch(() => {});
  }, []);

  const loadTasks = useCallback(() => {
    fetchTasks().then(setTasks).catch(() => {});
  }, []);

  useEffect(() => {
    loadAgents();
    loadTasks();
    const i1 = setInterval(loadAgents, 10000);
    const i2 = setInterval(loadTasks, 3000);
    return () => {
      clearInterval(i1);
      clearInterval(i2);
    };
  }, [loadAgents, loadTasks]);

  const handleTaskCreated = (task) => {
    setTasks((prev) => [task, ...prev]);
  };

  const handleTaskCancelled = (taskId) => {
    setTasks((prev) =>
      prev.map((t) =>
        t.task_id === taskId ? { ...t, state: "canceled" } : t
      )
    );
    setSelectedTask(null);
  };

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white font-bold text-sm">
              MC
            </div>
            <h1 className="text-lg font-bold text-white">Mission Control</h1>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">
              {agents.filter((a) => a.status === "online").length}/
              {agents.length} agents online
            </span>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-6 py-6 space-y-8">
        <AgentPanel onSelectAgent={() => {}} />

        <TaskLauncher agents={agents} onTaskCreated={handleTaskCreated} />

        {/* Tab navigation */}
        <div className="flex gap-1 border-b border-slate-800">
          <button
            onClick={() => setTab("board")}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === "board"
                ? "border-indigo-500 text-white"
                : "border-transparent text-slate-400 hover:text-white"
            }`}
          >
            Task Board
          </button>
          <button
            onClick={() => setTab("history")}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === "history"
                ? "border-indigo-500 text-white"
                : "border-transparent text-slate-400 hover:text-white"
            }`}
          >
            History
          </button>
        </div>

        {tab === "board" && (
          <TaskBoard tasks={tasks} onSelectTask={setSelectedTask} />
        )}
        {tab === "history" && (
          <TaskHistory tasks={tasks} onSelectTask={setSelectedTask} />
        )}
      </main>

      {/* Task detail drawer */}
      <TaskDetailDrawer
        task={selectedTask}
        onClose={() => setSelectedTask(null)}
        onCancelled={handleTaskCancelled}
      />
    </div>
  );
}

export default App;
