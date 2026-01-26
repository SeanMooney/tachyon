#!/bin/bash
#
# plugin.sh - DevStack plugin dispatch script for Tachyon
#
# This script is called by DevStack at various points during stack.sh,
# unstack.sh, and clean.sh execution.
#
# Supported services:
#   neo4j       - Neo4j graph database (Tachyon's backend)
#   tachyon-api - Tachyon API service (Placement replacement)
#
# Usage in local.conf:
#   enable_plugin tachyon https://opendev.org/openstack/tachyon
#   enable_service neo4j
#   enable_service tachyon-api

# Save trace setting
_XTRACE_TACHYON_PLUGIN=$(set +o | grep xtrace)
set +o xtrace

# Source the library functions
source $DEST/tachyon/devstack/lib/tachyon

# =============================================================================
# Neo4j Service Handling
# =============================================================================
if is_service_enabled neo4j; then

    if [[ "$1" == "stack" && "$2" == "pre-install" ]]; then
        # Install Neo4j in pre-install phase (system package)
        echo_summary "Installing Neo4j"
        install_neo4j

    elif [[ "$1" == "stack" && "$2" == "install" ]]; then
        # Configure Neo4j after system packages are installed
        echo_summary "Configuring Neo4j"
        configure_neo4j

    # NOTE: Neo4j is started by the overridden init_placement function in
    # lib/tachyon, which is called by stack.sh at the correct point in the
    # service startup sequence (after Keystone, before Nova).
    fi

    if [[ "$1" == "unstack" ]]; then
        echo_summary "Stopping Neo4j"
        stop_neo4j
    fi

    if [[ "$1" == "clean" ]]; then
        echo_summary "Cleaning Neo4j"
        cleanup_neo4j
    fi
fi

# =============================================================================
# Tachyon API Service Handling
# =============================================================================
if is_service_enabled tachyon-api; then

    if [[ "$1" == "stack" && "$2" == "install" ]]; then
        # Install Tachyon from source
        echo_summary "Installing Tachyon"
        install_tachyon

    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        # Configure Tachyon after layer 1 & 2 services are configured
        echo_summary "Configuring Tachyon"
        configure_tachyon

        # Create Keystone accounts (registers as placement service type)
        if is_service_enabled keystone; then
            create_tachyon_accounts
        fi

    # NOTE: Tachyon init and start are handled by the overridden init_placement
    # and start_placement functions in lib/tachyon. This ensures Tachyon starts
    # at the exact same point in the stack.sh flow where placement would
    # normally start (after Keystone, before Nova).

    elif [[ "$1" == "stack" && "$2" == "test-config" ]]; then
        # Configure for testing (e.g., tempest)
        echo_summary "Configuring Tachyon for testing"
        # Placement tempest tests should work against Tachyon since it uses
        # the same service type and API
        :
    fi

    if [[ "$1" == "unstack" ]]; then
        echo_summary "Stopping Tachyon"
        stop_tachyon
    fi

    if [[ "$1" == "clean" ]]; then
        echo_summary "Cleaning Tachyon"
        cleanup_tachyon
    fi
fi

# Restore xtrace
$_XTRACE_TACHYON_PLUGIN
