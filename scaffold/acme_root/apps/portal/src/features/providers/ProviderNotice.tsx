import { Link } from "react-router-dom";
import { Banner } from "../../design/kit";
import { shortTime } from "../sessions/sessionsModel";
import { noticeLine } from "./outageModel";
import { useOutageVm } from "./useOutageVm";

/** The banner a page shows above its title while the org's sessions wait on
 * a model provider; nothing otherwise. A missing key links to where one is
 * saved. */
export function ProviderNotice() {
  const vm = useOutageVm();
  if (vm.notices.length === 0) return null;
  return (
    <Banner>
      {vm.notices.map((notice) => (
        <div key={`${notice.provider}:${notice.cause}:${notice.detail}`} data-outage={notice.cause}>
          {noticeLine(notice, shortTime)}
          {notice.cause === "key" ? (
            <>
              {" "}
              <Link to="/models">Save a key</Link>
            </>
          ) : null}
        </div>
      ))}
    </Banner>
  );
}
