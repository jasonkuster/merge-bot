# merge-bot

Mergebot is a bot for automatically merging pull requests with a mainline repository. It was written for the Apache Infrastructure team by Jason Kuster.

## Usage

Authorized committers can comment on a pull request `@apache-merge-bot merge`. Merge bot polls repositories once per minute and upon seeing a request to merge will begin the merge process.
