-- Allow Sentinel-vetted Forge picks to enter the production HIL queue.
alter table private.hil_reviews
  drop constraint if exists hil_reviews_source_provider_chk;

alter table private.hil_reviews
  add constraint hil_reviews_source_provider_chk
  check (
    source_provider in (
      'cj_dropshipping',
      'browserbase_marketplace',
      'forge_sentinel'
    )
  );
