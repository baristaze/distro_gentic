// An address the portal moved: it sends the browser on to the new one, in
// place of the old in the history, so Back never lands on it again.
import { Navigate, useLocation, useParams } from "react-router-dom";
import { movedTo } from "./movedModel";

export function Moved({ to }: { to: string }) {
  const params = useParams();
  const location = useLocation();
  return <Navigate to={movedTo(to, params, location.search, location.hash)} replace state={location.state} />;
}
