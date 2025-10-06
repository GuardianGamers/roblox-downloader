#!/bin/bash
# Script to complete gameservers integration
# This updates ecs_task.py and template.yaml with the necessary changes

set -e

echo "Completing gameservers integration..."

# 1. Update ecs_task.py - add import
if ! grep -q "from update_gameservers import update_gameservers" ecs_task.py; then
    echo "Adding gameservers import to ecs_task.py..."
    sed -i.bak 's/^from pathlib import Path$/from pathlib import Path\nfrom update_gameservers import update_gameservers/' ecs_task.py
fi

# 2. Update ecs_task.py - add environment variable parsing
if ! grep -q "UPDATE_GAMESERVERS" ecs_task.py; then
    echo "Adding UPDATE_GAMESERVERS environment variable to ecs_task.py..."
    sed -i.bak "/force = os.environ.get('FORCE'/a\\
    update_games = os.environ.get('UPDATE_GAMESERVERS', 'true').lower() == 'true'" ecs_task.py
fi

# 3. Update ecs_task.py - add gameservers update logic before final return
# This is more complex, so print instructions
echo ""
echo "============================================"
echo "Manual step needed for ecs_task.py:"
echo "============================================"
echo "Add this code BEFORE the final 'return result' in ecs_task.py main():"
echo ""
cat << 'EOF'
        # Update gameservers if requested
        if update_games and action in ['all', 'gameservers']:
            print("\n" + "=" * 60)
            print("UPDATING GAMESERVERS")
            print("=" * 60)
            
            gameservers_result = update_gameservers(
                bucket_name=bucket_name,
                s3_prefix=""  # Store in root of bucket under gameservers/
            )
            
            # Merge results
            result_body = json.loads(result['body'])
            gameservers_body = json.loads(gameservers_result['body'])
            result_body['gameservers'] = gameservers_body
            result['body'] = json.dumps(result_body)
EOF

echo ""
echo "============================================"
echo "Manual step needed for template.yaml:"
echo "============================================"
echo "1. Change ACTION from 'download' to 'all'"
echo "2. Add these environment variables:"
echo ""
cat << 'EOF'
                  - Name: UPDATE_GAMESERVERS
                    Value: "true"
EOF

echo ""
echo "3. Add this IAM policy to RobloxDownloaderTaskRole:"
echo ""
cat << 'EOF'
        - PolicyName: BedrockAccess
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - bedrock:InvokeModel
                Resource:
                  - !Sub "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
EOF

echo ""
echo "4. Add s3:ListObjectsV2 to S3Access policy actions"
echo ""
echo "============================================"
echo "See GAMESERVERS_INTEGRATION.md for full details"
echo "============================================"
