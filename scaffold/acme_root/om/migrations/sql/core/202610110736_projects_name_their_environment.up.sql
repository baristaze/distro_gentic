-- A project may name the environment its sessions' workspaces start from:
-- an image, the commands that set it up, and the package registries its
-- setup reaches. Every project there is names none, and its sessions work
-- as before.

ALTER TABLE core.projects ADD COLUMN environment jsonb;
