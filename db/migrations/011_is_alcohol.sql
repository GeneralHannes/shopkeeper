-- shopkeeper schema v11: explicit alcohol flag so the add form never mis-sorts
-- premium alcohol vs general. Set from the General/Alcohol mode at add time.
-- Backfills existing rows: anything with drink info or an alcohol-ish category
-- becomes alcohol; beer stays general. Runs once.

BEGIN;

ALTER TABLE items ADD COLUMN IF NOT EXISTS is_alcohol boolean NOT NULL DEFAULT false;

UPDATE items SET is_alcohol = true
WHERE is_alcohol = false
  AND (
    style IS NOT NULL OR vintage IS NOT NULL OR abv IS NOT NULL OR origin IS NOT NULL
    OR lower(coalesce(category, '')) IN (
      'wine','red wine','white wine','rose','rosé','sparkling','champagne','prosecco',
      'whisky','whiskey','bourbon','scotch','vodka','rum','gin','brandy','tequila','mezcal',
      'cognac','liqueur','sake','soju','baijiu','rice wine','spirits','spirit','port','sherry','vermouth'
    )
  );

COMMIT;
