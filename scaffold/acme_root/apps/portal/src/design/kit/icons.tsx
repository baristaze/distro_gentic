// The kit's icons. An icon is drawn in the text's color and hidden from
// assistive technology; the words beside it, or the label of the button it
// sits in, are what a screen reader says.
//
// Every drawing but the gear is Lucide's, from `lucide-react` (ISC; its
// license ships with the package). `kitIcon` draws any Lucide icon the
// kit's way, so a product takes one the platform does not name from
// `lucide-react` and passes it through here.
import type { JSX } from "react";
import type { LucideIcon, LucideProps } from "lucide-react";
import {
  Archive,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  BellRing,
  BookOpen,
  Bot,
  Building2,
  ChartColumn,
  Check,
  ChevronDown,
  ChevronRight,
  CornerLeftUp,
  CircleX,
  ClipboardCheck,
  Copy,
  Crosshair,
  Crown,
  ExternalLink,
  Eye,
  FileDiff,
  FileText,
  Fingerprint,
  Flag,
  FolderGit2,
  GitPullRequest,
  Info,
  Keyboard,
  KeyRound,
  LayoutList,
  ListChecks,
  ListFilter,
  ListTree,
  LoaderCircle,
  LogOut,
  MessageCircleQuestionMark,
  MessageSquareText,
  Monitor,
  Moon,
  Network,
  PanelLeft,
  PanelRight,
  Pause,
  Play,
  Plus,
  ScrollText,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  SquarePen,
  SquareTerminal,
  Sun,
  User,
  UserPlus,
  Users,
  X,
  Zap,
} from "lucide-react";

export type { LucideIcon };

/** An icon of the kit: drawn at 16 pixels, hidden from assistive technology. */
export type KitIcon = (props: Omit<LucideProps, "ref">) => JSX.Element;

/** One Lucide icon at the kit's size: its 24-unit grid drawn at 16 pixels,
 * so its 2-unit stroke is the 1.3-pixel line of the kit's own marks. */
export function kitIcon(Icon: LucideIcon): KitIcon {
  return function Drawn(props) {
    return <Icon size={16} aria-hidden="true" focusable="false" style={{ flexShrink: 0 }} {...props} />;
  };
}

/** A gear: Settings. The product's own drawing. */
export function SettingsIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false" style={{ flexShrink: 0 }}>
      <path
        d="M6.6 1.75h2.8l.4 1.9 1.2.7 1.85-.6 1.4 2.4-1.45 1.3v1.1l1.45 1.3-1.4 2.4-1.85-.6-1.2.7-.4 1.9H6.6l-.4-1.9-1.2-.7-1.85.6-1.4-2.4L3.2 8.55v-1.1L1.75 6.15l1.4-2.4L5 4.35l1.2-.7z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
      <circle cx="8" cy="8" r="2" fill="none" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

/** A screen: follow the system. */
export const MonitorIcon = kitIcon(Monitor);
/** The sun: the light theme. */
export const SunIcon = kitIcon(Sun);
/** The moon: the dark theme. */
export const MoonIcon = kitIcon(Moon);
/** A door with an arrow out: Sign out. */
export const LogOutIcon = kitIcon(LogOut);
/** One person: a personal org, a profile. */
export const UserIcon = kitIcon(User);
/** Two people: a team org, the members. */
export const UsersIcon = kitIcon(Users);
/** A person with a plus: invite someone. */
export const UserPlusIcon = kitIcon(UserPlus);
/** A plus: make a new one. */
export const PlusIcon = kitIcon(Plus);
/** A crown: the owner. */
export const CrownIcon = kitIcon(Crown);
/** A shield: an admin. */
export const ShieldIcon = kitIcon(Shield);
/** An eye: one who reads. */
export const EyeIcon = kitIcon(Eye);
/** A face with an antenna: an agent. */
export const BotIcon = kitIcon(Bot);
/** A magnifier: search. */
export const SearchIcon = kitIcon(Search);
/** A pen on a square: a new session. */
export const NewSessionIcon = kitIcon(SquarePen);
/** A bolt: an automation. */
export const AutomationIcon = kitIcon(Zap);
/** An open book: the knowledge base. */
export const KnowledgeIcon = kitIcon(BookOpen);
/** A list of rows: every session. */
export const ListIcon = kitIcon(LayoutList);
/** Lines that narrow: a filter. */
export const FilterIcon = kitIcon(ListFilter);
/** A window with its side pane: the sidebar. */
export const SidebarIcon = kitIcon(PanelLeft);
/** A keyboard: the shortcuts. */
export const KeyboardIcon = kitIcon(Keyboard);
/** A box with an arrow out: a page outside the app. */
export const ExternalIcon = kitIcon(ExternalLink);
/** A page: the documentation. */
export const DocumentIcon = kitIcon(FileText);
/** A folder with a branch: a project. */
export const ProjectIcon = kitIcon(FolderGit2);
/** An arrow up: send. */
export const SendIcon = kitIcon(ArrowUp);
/** An i in a circle: what a field means. */
export const InfoIcon = kitIcon(Info);
/** A chevron down: a chip that opens a menu. */
export const ChevronIcon = kitIcon(ChevronDown);
/** A box: archived. */
export const ArchiveIcon = kitIcon(Archive);
/** A chevron right: a folded row that opens. */
export const ChevronRightIcon = kitIcon(ChevronRight);
/** A check: a call that answered. */
export const CheckIcon = kitIcon(Check);
/** A crossed circle: a call that failed or was denied. */
export const FailedIcon = kitIcon(CircleX);
/** A turning circle: a call that runs. */
export const SpinnerIcon = kitIcon(LoaderCircle);
/** A shield with a mark: a call that waits for a person's decision. */
export const HeldIcon = kitIcon(ShieldAlert);
/** Two bars: pause. */
export const PauseIcon = kitIcon(Pause);
/** A triangle: resume. */
export const PlayIcon = kitIcon(Play);
/** A panel on the right: show or hide the session's panel. */
export const PanelIcon = kitIcon(PanelRight);
/** Two sheets: copy. */
export const CopyIcon = kitIcon(Copy);
/** An arrow down: jump to the latest. */
export const JumpIcon = kitIcon(ArrowDown);
/** A pull request. */
export const PullRequestIcon = kitIcon(GitPullRequest);
/** A checked list: a plan. */
export const PlanIcon = kitIcon(ListChecks);
/** A shield with a check: a validation. */
export const ValidationIcon = kitIcon(ShieldCheck);
/** A flag: a result. */
export const ResultIcon = kitIcon(Flag);
/** Linked nodes: a sub-agent. */
export const SubAgentIcon = kitIcon(Network);
/** A speech bubble with a question mark: the agent asks. */
export const AskIcon = kitIcon(MessageCircleQuestionMark);
/** A speech bubble with lines: a sub-agent's report. */
export const ReportIcon = kitIcon(MessageSquareText);
/** An arrow up and back: what the parent asked. */
export const ParentIcon = kitIcon(CornerLeftUp);
/** A tree of lines: the timeline's outline. */
export const OutlineIcon = kitIcon(ListTree);
/** A ringing bell: a session needs the person. */
export const NeedsYouIcon = kitIcon(BellRing);
/** A terminal: a session's workspace. */
export const WorkspaceIcon = kitIcon(SquareTerminal);
/** Crosshairs: one step. */
export const StepIcon = kitIcon(Crosshair);
/** A file with a diff: what a session changed. */
export const ChangesIcon = kitIcon(FileDiff);
/** A clipboard with a check: evidence. */
export const EvidenceIcon = kitIcon(ClipboardCheck);
/** A cross: close a tab. */
export const CloseTabIcon = kitIcon(X);

/** An arrow to the left: back to where the person came from. */
export const BackIcon = kitIcon(ArrowLeft);

/** A building: the organization. */
export const OrgIcon = kitIcon(Building2);

/** A key: an API key. */
export const KeyIcon = kitIcon(KeyRound);

/** A fingerprint: signing in. */
export const SignOnIcon = kitIcon(Fingerprint);

/** Columns: what was spent. */
export const UsageIcon = kitIcon(ChartColumn);

/** A scroll: the record of what happened. */
export const AuditIcon = kitIcon(ScrollText);
