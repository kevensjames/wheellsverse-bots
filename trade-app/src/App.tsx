import {
  createBrowserRouter,
  Navigate,
  RouterProvider,
} from "react-router-dom";
import type { ReactNode } from "react";
import { Layout } from "./components/Layout";
import { isAuthenticated } from "./lib/auth";
import { Landing } from "./pages/Landing";
import { Login } from "./pages/Login";
import { Signup } from "./pages/Signup";
import { Dashboard } from "./pages/Dashboard";
import { Pricing } from "./pages/Pricing";
import { BillingSuccess } from "./pages/BillingSuccess";
import { BillingCancel } from "./pages/BillingCancel";

function ProtectedRoute({ children }: { children: ReactNode }) {
  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Landing /> },
      { path: "/login", element: <Login /> },
      { path: "/signup", element: <Signup /> },
      {
        path: "/dashboard",
        element: (
          <ProtectedRoute>
            <Dashboard />
          </ProtectedRoute>
        ),
      },
      {
        path: "/pricing",
        element: (
          <ProtectedRoute>
            <Pricing />
          </ProtectedRoute>
        ),
      },
      {
        path: "/billing/success",
        element: (
          <ProtectedRoute>
            <BillingSuccess />
          </ProtectedRoute>
        ),
      },
      {
        path: "/billing/cancel",
        element: (
          <ProtectedRoute>
            <BillingCancel />
          </ProtectedRoute>
        ),
      },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
