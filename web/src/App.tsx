import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./lib/auth";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";
import Login from "./pages/Login";
import Inbox from "./pages/Inbox";
import SheetPage from "./pages/Sheet";
import Posts from "./pages/Posts";
import PostPage from "./pages/Post";
import Upload from "./pages/Upload";
import Scoring from "./pages/Scoring";
import JudgeLab from "./pages/JudgeLab";
import Members from "./pages/Members";
import Offenders from "./pages/Offenders";

export default function App() {
  const { session, role, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!session || !role) return <Login />;
  const admin = role === "admin";
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Inbox />} />
          <Route path="sheets/:id" element={<SheetPage />} />
          <Route path="posts" element={<Posts />} />
          <Route path="posts/:code" element={<PostPage />} />
          <Route path="offenders" element={<Offenders />} />
          {admin && <Route path="upload" element={<Upload />} />}
          {admin && <Route path="scoring" element={<Scoring />} />}
          {admin && <Route path="judge" element={<JudgeLab />} />}
          {admin && <Route path="members" element={<Members />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
